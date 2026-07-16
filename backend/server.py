"""QMTServer 核心模块。

注册所有 API 端点（管理、策略、交易、聚宽下单、信号），
管理 QMT 连接、策略生命周期、Token 认证与信号日志。
"""
from fastapi import FastAPI, HTTPException, Header, Depends, Path, Request
from pydantic import BaseModel
import inspect
import secrets
import asyncio
from typing import Any, Optional
from datetime import datetime, timezone
from backend.qmt_client import create_trader
from backend.strategy_manager import StrategyManager, StrategyCreate, StrategyUpdate, PositionAssignment
from backend.utils import fetch_preclose_from_xtdata, fetch_stock_names_from_xtdata, normalize_to_qmt
from backend.jukuan_orders import JukuanOrderHandler
import uvicorn
from backend.order_tracker import OrderTracker, OrderState
from backend.db.repositories.order import OrderRepository, InMemoryOrderRepository
from backend.db.repositories.strategy import StrategyRepository, InMemoryStrategyRepository
from backend.db.repositories.signal_log import SignalLogRepository, InMemorySignalLogRepository
from backend.db.models.signal_log import SignalLogModel
from backend.db.repositories.account import AccountRepository, InMemoryAccountRepository
from backend.db.models.account import AccountModel
from backend.logger import logger
from config.settings import settings

_current_server = None


def _get_client_ip(raw_request: Optional[Request]) -> Optional[str]:
    """获取客户端真实 IP，优先读取反向代理头。"""
    if raw_request is None:
        return None
    forwarded = raw_request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    real_ip = raw_request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return raw_request.client.host if raw_request.client else None


async def _verify_token(x_token: str = Header(...)):
    if _current_server is None:
        raise HTTPException(status_code=401, detail="服务器未运行")
    if x_token != _current_server.token:
        raise HTTPException(status_code=401, detail="无效的Token")
    return x_token


async def _verify_any_token(x_token: str = Header(...)):
    if _current_server is None:
        raise HTTPException(status_code=401, detail="服务器未运行")
    if x_token == _current_server.token:
        return x_token
    strategy = _current_server.strategy_manager.find_by_token(x_token)
    if strategy and strategy.enabled:
        return x_token
    raise HTTPException(status_code=401, detail="无效的Token")


class QMTServer:
    def __init__(self, account_id: str, mini_qmt_path: str,
                 host: str = "0.0.0.0", port: int = 8000, token: str = None,
                 strategy_repository: Optional[StrategyRepository] = None,
                 order_repository: Optional[OrderRepository] = None,
                 signal_log_repository: Optional[SignalLogRepository] = None,
                 account_repository: Optional[AccountRepository] = None,
                 db_session=None):
        global _current_server
        _current_server = self
        self.account_id = account_id
        self.mini_qmt_path = mini_qmt_path
        self.host = host
        self.port = port
        self.app = FastAPI(title="QMT Live Assistant")
        self.trader = None
        self.account = None
        self.callback = None
        self.token = token if token else self.generate_token()
        self._db_session = db_session
        self._account_repository = account_repository
        self._signal_log_repository = signal_log_repository
        self.order_tracker = OrderTracker(repository=order_repository)
        self._poll_task: Optional[asyncio.Task] = None
        self._jukuan_handler = None
        self.running = False
        self.strategy_manager = StrategyManager(repository=strategy_repository)
        self._register_order_state_callback()
        print(f"\n授权Token: {self.token}\n")

    def generate_token(self) -> str:
        secets_token = secrets.token_hex(32)
        return secets_token

    async def verify_token(self, x_token: str = Header(...)):
        return await _verify_token(x_token)

    async def verify_any_token(self, x_token: str = Header(...)):
        return await _verify_any_token(x_token)

    def init_trader(self):
        self.trader, self.account, self.callback = create_trader(
            self.account_id, self.mini_qmt_path,
            order_tracker=self.order_tracker
        )

    def _register_order_state_callback(self):
        """注册订单状态变更回调，用于在终态时修正策略持仓。"""
        def on_state_change(order):
            if not order.strategy_id or not order.optimistic_position_applied:
                return

            if order.status == OrderState.FILLED:
                self.strategy_manager.reconcile_position(
                    order.strategy_id,
                    order.stock_code,
                    order.direction,
                    order.quantity,
                    order.filled_quantity,
                    order.filled_price,
                    order.optimistic_snapshot,
                )
            elif order.status == OrderState.FAILED:
                self.strategy_manager.rollback_position(
                    order.strategy_id, order.optimistic_snapshot
                )

        self.order_tracker.on_state_change(on_state_change)

    def _track_and_apply_order(self, order_result: dict, strategy_id: Optional[str],
                               strategy_name: str, stock_name: str = "") -> None:
        """将订单注册到跟踪器；乐观冻结已在下单前完成，这里仅传递快照。"""
        order_id = order_result.get('order_id')
        if not order_id:
            return
        print(f"跟踪订单 {order_id}，策略: {strategy_name}, 策略ID: {strategy_id}")
        jq_code = order_result.get('jq_code', '')
        direction = order_result.get('direction', '')
        quantity = order_result.get('quantity', 0)
        price = order_result.get('price', 0.0)
        order_type = order_result.get('order_type', 0)
        qmt_code = order_result.get('qmt_code') or normalize_to_qmt(jq_code)

        snapshot = order_result.get('optimistic_snapshot')
        optimistic_applied = snapshot is not None

        self.order_tracker.track_order(
            order_id=order_id,
            stock_code=qmt_code,
            jq_code=jq_code,
            stock_name=stock_name,
            direction=direction,
            quantity=quantity,
            order_type=order_type,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            price=price,
            optimistic_position_applied=optimistic_applied,
            optimistic_snapshot=snapshot,
        )

    async def _poll_orders_loop(self):
        """后台轮询 pending 订单状态，补偿漏掉的回调。"""
        try:
            while self.running:
                try:
                    if self.trader is not None and self.account is not None:
                        await self.order_tracker.poll_and_reconcile(
                            self.trader, self.account
                        )
                except Exception:
                    # 轮询失败不应影响主服务
                    pass
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    def convert_to_dict(self, obj):
        if isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        elif isinstance(obj, dict):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [self.convert_to_dict(item) for item in obj]
        elif hasattr(obj, '__dir__'):
            attrs = obj.__dir__()
            public_attrs = {
                attr: getattr(obj, attr)
                for attr in attrs
                if not attr.startswith('_') and not callable(getattr(obj, attr))
            }
            return public_attrs
        return str(obj)

    def _query_account_positions(self):
        """查询账户持仓列表，包含名称、每日盈亏和总盈亏。"""
        positions = []
        try:
            qmt_positions_raw = self.trader.query_stock_positions(self.account)
            stock_codes = set()
            qmt_positions = []
            for p in qmt_positions_raw:
                code = getattr(p, 'stock_code', '')
                vol = getattr(p, 'volume', 0) or 0
                mv = getattr(p, 'market_value', 0.0) or 0.0
                open_pr = getattr(p, 'open_price', 0.0) or 0.0
                can_use = getattr(p, 'can_use_volume', 0) or 0
                if code and vol > 0:
                    qmt_positions.append({
                        "stock_code": code,
                        "volume": vol,
                        "market_value": mv,
                        "open_price": open_pr,
                        "can_use_volume": can_use,
                    })
                    stock_codes.add(code)

            name_map = fetch_stock_names_from_xtdata(stock_codes)
            preclose_map = fetch_preclose_from_xtdata(stock_codes)
            for pos in qmt_positions:
                pos["stock_name"] = name_map.get(pos["stock_code"], "")
                preclose = preclose_map.get(pos["stock_code"])
                if preclose is not None and preclose > 0:
                    pos_daily_pnl = round(pos["market_value"] - preclose * pos["volume"], 2)
                else:
                    pos_daily_pnl = 0.0
                pos["daily_pnl"] = pos_daily_pnl

                op = pos.get("open_price", 0)
                if op > 0 and pos["volume"] > 0:
                    pos["total_pnl"] = round(pos["market_value"] - op * pos["volume"], 2)
                else:
                    pos["total_pnl"] = 0.0

                positions.append(pos)
        except Exception:
            pass
        return positions

    def convert_method_to_endpoint(self, method_name: str, method, target_app):
        sig = inspect.signature(method)
        param_names = list(sig.parameters.keys())

        class_fields = {'__annotations__': {}}
        for param in param_names:
            if param in ['self', 'account']:
                continue
            class_fields['__annotations__'][param] = Any
            class_fields[param] = None

        RequestModel = type(f'{method_name}Request', (BaseModel,), class_fields)

        async def endpoint(request: RequestModel, token: str = Depends(_verify_token)):
            try:
                params = request.dict(exclude_unset=True)
                if 'account' in param_names:
                    params['account'] = _current_server.account
                result = getattr(_current_server.trader, method_name)(**params)
                converted_result = _current_server.convert_to_dict(result)
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        target_app.post(f'/api/{method_name}')(endpoint)

    def setup_routes(self, target_app=None):
        app = target_app or self.app

        if self.trader is not None:
            trader_methods = inspect.getmembers(
                self.trader.__class__,
                predicate=lambda x: inspect.isfunction(x) or inspect.ismethod(x)
            )

            excluded_methods = {
                '__init__', '__del__', 'register_callback', 'start', 'stop',
                'connect', 'sleep', 'run_forever', 'set_relaxed_response_order_enabled'
            }

            for method_name, method in trader_methods:
                if not method_name.startswith('_') and method_name not in excluded_methods:
                    self.convert_method_to_endpoint(method_name, method, app)

        @app.get('/api/server-status')
        async def server_status():
            return {
                'success': True,
                'data': {
                    'running': _current_server.running if _current_server else False,
                    'account_id': _current_server.account_id if _current_server else None,
                    'qmt_path': _current_server.mini_qmt_path if _current_server else None,
                    'host': _current_server.host if _current_server else None,
                    'port': _current_server.port if _current_server else None,
                }
            }

        @app.get('/api/test-connection')
        async def test_connection(token: str = Depends(_verify_token)):
            try:
                if _current_server.trader is None:
                    _current_server.init_trader()
                result = _current_server.trader.query_stock_asset(_current_server.account)
                converted_result = _current_server.convert_to_dict(result)
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"连接测试失败: {str(e)}")

        @app.get('/api/orders')
        async def get_orders(
            status: Optional[str] = None,
            strategy_name: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            token: str = Depends(_verify_token),
        ):
            orders = _current_server.order_tracker.list_all()
            result = []
            for o in orders:
                result.append({
                    "order_id": o.order_id,
                    "stock_code": o.stock_code,
                    "stock_name": o.stock_name,
                    "jq_code": o.jq_code,
                    "direction": o.direction,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "filled_price": o.filled_price,
                    "price": o.price,
                    "status": o.status,
                    "order_type": o.order_type,
                    "strategy_id": o.strategy_id,
                    "strategy_name": o.strategy_name,
                    "placed_at": o.placed_at.isoformat() if o.placed_at else None,
                    "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
                    "error_msg": o.error_msg,
                })

            if status:
                result = [o for o in result if o["status"] == status]
            if strategy_name:
                result = [o for o in result if o["strategy_name"] == strategy_name]
            if start_date:
                result = [o for o in result if (o.get("placed_at") or "")[:10] >= start_date]
            if end_date:
                result = [o for o in result if (o.get("placed_at") or "")[:10] <= end_date]

            result.sort(key=lambda x: x.get("placed_at") or "", reverse=True)
            return {'success': True, 'data': result}

        @app.get('/api/signal-logs')
        async def get_signal_logs(
            status: Optional[str] = None,
            strategy_name: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            token: str = Depends(_verify_token),
        ):
            if _current_server._signal_log_repository is None:
                return {'success': True, 'data': []}

            strategies = _current_server.strategy_manager.list_all()
            strategy_map = {s['id']: s['name'] for s in strategies}
            name_to_id = {s['name']: s['id'] for s in strategies}

            filters = {}
            if strategy_name:
                strategy_id = name_to_id.get(strategy_name)
                if strategy_id:
                    filters['strategy_id'] = strategy_id
                else:
                    return {'success': True, 'data': []}

            logs = _current_server._signal_log_repository.list_all(**filters)

            result = []
            for log in logs:
                is_error = bool(log.error_msg)
                if status == 'error' and not is_error:
                    continue
                if status == 'success' and is_error:
                    continue

                received_at = log.received_at.isoformat() if log.received_at else None
                date_part = (received_at or '')[:10]
                if start_date and date_part < start_date:
                    continue
                if end_date and date_part > end_date:
                    continue

                result.append({
                    "id": log.id,
                    "strategy_id": log.strategy_id,
                    "strategy_name": strategy_map.get(log.strategy_id, log.strategy_id or '--'),
                    "endpoint": log.endpoint,
                    "source_platform": log.source_platform,
                    "payload": log.payload,
                    "processed_order_id": log.processed_order_id,
                    "error_msg": log.error_msg,
                    "received_at": received_at,
                    "status": "error" if is_error else "success",
                })

            result.sort(key=lambda x: x.get("received_at") or "", reverse=True)
            return {'success': True, 'data': result}

        @app.get('/api/account-asset')
        async def account_asset(token: str = Depends(_verify_token)):
            try:
                result = _current_server.trader.query_stock_asset(_current_server.account)
                converted_result = _current_server.convert_to_dict(result)

                positions = _current_server._query_account_positions()
                daily_profit = round(sum(p.get('daily_pnl', 0) for p in positions), 2)

                converted_result['daily_profit'] = daily_profit
                converted_result['positions'] = positions
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get('/api/account-positions')
        async def account_positions(token: str = Depends(_verify_token)):
            try:
                positions = _current_server._query_account_positions()
                return {'success': True, 'data': positions}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post('/api/convert/jq-to-qmt')
        async def convert_jq_to_qmt(request: dict):
            from backend.utils import jq_to_qmt
            code = request.get('code', '')
            return {'success': True, 'data': {'result': jq_to_qmt(code)}}

        @app.post('/api/convert/qmt-to-jq')
        async def convert_qmt_to_jq(request: dict):
            from backend.utils import qmt_to_jq
            code = request.get('code', '')
            return {'success': True, 'data': {'result': qmt_to_jq(code)}}

        # --- 聚宽风格下单 API ---

        def _resolve_strategy(request: dict, x_token: str):
            """解析 token，返回 (strategy_name, strategy_id)，非策略 token 返回 (None, None)"""
            if x_token == _current_server.token:
                return None, None
            strategy = _current_server.strategy_manager.find_by_token(x_token)
            if not strategy or not strategy.enabled:
                raise HTTPException(status_code=401, detail="无效的Token")
            return strategy.name, strategy.id

        def _get_jukuan_handler():
            if _current_server._jukuan_handler is None:
                _current_server._jukuan_handler = JukuanOrderHandler(
                    trader=_current_server.trader,
                    account=_current_server.account,
                    strategy_manager=_current_server.strategy_manager,
                )
            return _current_server._jukuan_handler

        async def _jukuan_endpoint(request: dict, x_token: str, method_name: str,
                                   raw_request: Optional[Request] = None):
            strategy_name, strategy_id = _resolve_strategy(request, x_token)
            if strategy_id is None:
                raise HTTPException(status_code=403, detail="聚宽下单接口仅支持策略Token")
            handler = _get_jukuan_handler()

            security = request.get('security', '').strip()
            if not security:
                raise HTTPException(status_code=400, detail="请提供 security 参数")

            client_ip = _get_client_ip(raw_request)
            logger.info(
                "【下单请求】endpoint=/api/%s ip=%s strategy=%s(%s) security=%s "
                "side=%s amount=%s value=%s source_platform=%s",
                method_name,
                client_ip,
                strategy_name,
                strategy_id,
                security,
                request.get('side', 'long'),
                request.get('amount'),
                request.get('value'),
                request.get('source_platform'),
            )

            signal_log = None
            if _current_server._signal_log_repository is not None:
                signal_log = _current_server._signal_log_repository.add(
                    SignalLogModel(
                        strategy_id=strategy_id,
                        endpoint=f"/api/{method_name}",
                        source_platform=request.get("source_platform"),
                        source_ip=client_ip,
                        payload=request,
                        received_at=datetime.now(timezone.utc),
                        created_at=datetime.now(timezone.utc),
                    )
                )

            try:
                qmt_code = normalize_to_qmt(security)

                name_map = fetch_stock_names_from_xtdata({qmt_code})
                stock_name = name_map.get(qmt_code) or ""

                amount = request.get('amount', 0)
                value = request.get('value', 0)
                side = request.get('side', 'long')

                method = getattr(handler, method_name)
                if method_name in ('jukuan_order', 'jukuan_order_target'):
                    result = method(qmt_code, amount, side=side, strategy_id=strategy_id)
                else:
                    result = method(qmt_code, value, side=side, strategy_id=strategy_id)

                # 保留原始聚宽代码便于返回和日志
                result['jq_code'] = security

                # 注册订单到跟踪器，并对策略持仓进行乐观更新
                if result.get('order_id'):
                    result['strategy_name'] = strategy_name or method_name
                    _current_server._track_and_apply_order(
                        result, strategy_id, strategy_name or method_name, stock_name=stock_name
                    )

                # 策略记账
                if strategy_id and result.get('order_id'):
                    _current_server.strategy_manager.add_trading_record(strategy_id, {
                        'timestamp': datetime.now().isoformat(),
                        'stock_code': qmt_code,
                        'direction': result.get('direction', 'none'),
                        'quantity': result.get('quantity', 0),
                        'price': result.get('price', 0),
                        'order_id': str(result.get('order_id', '')),
                        'method': method_name,
                    })

                if signal_log is not None and _current_server._signal_log_repository is not None:
                    order_id = str(result.get('order_id', '')) if result.get('order_id') else None
                    _current_server._signal_log_repository.update_processed_order(
                        signal_log.id, order_id
                    )

                return {'success': True, 'data': result}
            except Exception as e:
                if signal_log is not None and _current_server._signal_log_repository is not None:
                    _current_server._signal_log_repository.update_error(signal_log.id, str(e))
                raise

        @app.post('/api/jukuan_order')
        async def jukuan_order_endpoint(request: dict, raw_request: Request, x_token: str = Header(...)):
            try:
                return await _jukuan_endpoint(request, x_token, 'jukuan_order', raw_request)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post('/api/jukuan_order_target')
        async def jukuan_order_target_endpoint(request: dict, raw_request: Request, x_token: str = Header(...)):
            try:
                return await _jukuan_endpoint(request, x_token, 'jukuan_order_target', raw_request)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post('/api/jukuan_order_value')
        async def jukuan_order_value_endpoint(request: dict, raw_request: Request, x_token: str = Header(...)):
            try:
                return await _jukuan_endpoint(request, x_token, 'jukuan_order_value', raw_request)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post('/api/jukuan_order_target_value')
        async def jukuan_order_target_value_endpoint(request: dict, raw_request: Request, x_token: str = Header(...)):
            try:
                return await _jukuan_endpoint(request, x_token, 'jukuan_order_target_value', raw_request)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # --- 策略管理 API ---

        def _enrich_order_count(strategies):
            for s in strategies:
                orders = _current_server.order_tracker.get_orders_by_strategy(s["id"])
                s["order_count"] = len(orders)
                frozen_cash = sum(
                    o.quantity * o.price
                    for o in orders
                    if o.direction == "buy"
                    and o.status in (OrderState.PENDING, OrderState.PARTIAL)
                    and o.optimistic_position_applied
                )
                s["frozen_cash"] = round(frozen_cash, 2)
                s["total_asset"] = round(s["total_asset"] + frozen_cash, 2)
            return strategies

        @app.get('/api/strategies')
        async def list_strategies(token: str = Depends(_verify_token)):
            strategies = _current_server.strategy_manager.list_all_enriched(
                _current_server.trader, _current_server.account
            )
            return {'success': True, 'data': _enrich_order_count(strategies)}

        @app.post('/api/strategies')
        async def create_strategy(data: StrategyCreate, token: str = Depends(_verify_token)):
            try:
                if data.positions:
                    normalized_positions = [
                        PositionAssignment(
                            stock_code=normalize_to_qmt(p.stock_code),
                            stock_name=p.stock_name,
                            quantity=p.quantity,
                            current_price=p.current_price,
                        )
                        for p in data.positions
                    ]
                    data = data.model_copy(update={'positions': normalized_positions})
                strategy = _current_server.strategy_manager.create(data)
                return {'success': True, 'data': strategy.model_dump()}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.put('/api/strategies/{strategy_id}')
        async def update_strategy(
            strategy_id: str = Path(...),
            data: StrategyUpdate = None,
            token: str = Depends(_verify_token),
        ):
            try:
                if data and data.positions:
                    normalized_positions = [
                        PositionAssignment(
                            stock_code=normalize_to_qmt(p.stock_code),
                            stock_name=p.stock_name,
                            quantity=p.quantity,
                            current_price=p.current_price,
                        )
                        for p in data.positions
                    ]
                    data = data.model_copy(update={'positions': normalized_positions})
                strategy = _current_server.strategy_manager.update(strategy_id, data)
                if not strategy:
                    raise HTTPException(status_code=404, detail="策略不存在")
                return {'success': True, 'data': strategy.model_dump()}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.delete('/api/strategies/{strategy_id}')
        async def delete_strategy(
            strategy_id: str = Path(...),
            token: str = Depends(_verify_token),
        ):
            if not _current_server.strategy_manager.delete(strategy_id):
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': {'message': '策略已删除'}}

        @app.post('/api/strategies/{strategy_id}/toggle')
        async def toggle_strategy(
            strategy_id: str = Path(...),
            token: str = Depends(_verify_token),
        ):
            strategy = _current_server.strategy_manager.toggle(strategy_id)
            if not strategy:
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': strategy.model_dump()}

        @app.post('/api/strategies/refresh')
        async def refresh_strategies(token: str = Depends(_verify_token)):
            strategies = _current_server.strategy_manager.list_all_enriched(
                _current_server.trader, _current_server.account
            )
            return {'success': True, 'data': _enrich_order_count(strategies)}

    def init_and_setup(self, target_app=None):
        try:
            self._ensure_account_record()
            self.init_trader()
        except Exception:
            self.setup_routes(target_app=target_app)
            raise
        self.order_tracker._load_orders()
        self.setup_routes(target_app=target_app)
        self.running = True
        self._poll_task = asyncio.create_task(self._poll_orders_loop())

    def _ensure_account_record(self):
        """如启用数据库，同步当前账户信息到 accounts 表。"""
        if self._db_session is None or self._account_repository is None:
            return
        account = self._account_repository.get_by_account_id(self.account_id)
        if account is not None:
            account.qmt_path = self.mini_qmt_path
            self._account_repository.update(account)
        else:
            account = AccountModel(
                name=self.account_id,
                account_id=self.account_id,
                qmt_path=self.mini_qmt_path,
            )
            self._account_repository.add(account)

    def stop(self):
        global _current_server
        self.running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._db_session is not None:
            self._db_session.close()
            self._db_session = None
        _current_server = None


def create_server(account_id: str, mini_qmt_path: str,
                  host: str = "0.0.0.0", port: int = 8000, token: str = None):
    return QMTServer(account_id, mini_qmt_path, host, port, token)
