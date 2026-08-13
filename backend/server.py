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
from backend.connection_watchdog import QMTConnectionWatchdog, ConnectionState
from backend.qmt_client import create_trader
from backend.strategy_manager import StrategyManager, StrategyCreate, StrategyUpdate, PositionAssignment
from backend.utils import fetch_preclose_from_xtdata, fetch_stock_names_from_xtdata, normalize_to_qmt, seconds_until_market_open, qmt_to_jq, qmt_call, run_blocking, BLOCKING_CALL_TIMEOUT_LONG, is_future, get_lot_size, get_quantity_unit
from backend.jukuan_orders import JukuanOrderHandler, InsufficientFundsError
import uvicorn
from backend.order_tracker import OrderTracker, OrderState
from backend.models.order import TrackedOrder, OrderResendRequest, ManualOrderRequest, GenericOrderRequest
from backend.db.repositories.order import OrderRepository, InMemoryOrderRepository
from backend.db.repositories.strategy import StrategyRepository, InMemoryStrategyRepository
from backend.db.repositories.signal_log import SignalLogRepository, InMemorySignalLogRepository
from backend.db.models.signal_log import SignalLogModel
from backend.db.repositories.account import AccountRepository, InMemoryAccountRepository
from backend.db.models.account import AccountModel
from backend.constants import STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import ORDER_TYPE_SET, PRICE_TYPE_SET, FIX_PRICE, LATEST_PRICE
from backend.source_platform_notifier import (
    notify_source_platform,
    resolve_webhook_url,
)
from backend.bark_service import BarkService, BarkConfig
from backend.pending_buy_manager import PendingBuyManager
from backend.db.repositories.settings import SettingsRepository
from config.settings import settings
import threading

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


async def _verify_strategy_token(x_token: str = Header(...)):
    """仅策略 Token 可用，校验通过后返回对应策略；QMT 未连接时 503。"""
    if _current_server is None:
        raise HTTPException(status_code=401, detail="服务器未运行")
    strategy = _current_server.strategy_manager.find_by_token(x_token)
    if strategy is None or not strategy.enabled:
        raise HTTPException(status_code=401, detail="无效的Token")
    if not _current_server.running:
        raise HTTPException(status_code=503, detail="服务未启动")
    if not _current_server.qmt_connected:
        detail = "QMT 连接断开，正在重连"
        if _current_server.last_connection_error:
            detail += f": {_current_server.last_connection_error}"
        raise HTTPException(status_code=503, detail=detail)
    return strategy


async def _require_qmt_connected(x_token: str = Header(...)):
    await _verify_token(x_token)
    if _current_server is None or not _current_server.running:
        raise HTTPException(status_code=503, detail="服务未启动")
    if not _current_server.qmt_connected:
        detail = "QMT 连接断开，正在重连"
        if _current_server.last_connection_error:
            detail += f": {_current_server.last_connection_error}"
        raise HTTPException(status_code=503, detail=detail)
    return x_token


class QMTServer:
    def __init__(self, account_id: str, mini_qmt_path: str,
                 host: str = settings.SERVER_HOST, port: int = settings.SERVER_PORT, token: str = None,
                 strategy_repository: Optional[StrategyRepository] = None,
                 order_repository: Optional[OrderRepository] = None,
                 signal_log_repository: Optional[SignalLogRepository] = None,
                 account_repository: Optional[AccountRepository] = None,
                 settings_repository: Optional[SettingsRepository] = None,
                 pending_buy_repository=None,
                 db_session=None):
        global _current_server
        _current_server = self
        self.account_id = account_id
        self.mini_qmt_path = mini_qmt_path
        self.host = host
        self.port = port
        self.app = FastAPI(title="QMT Live Assistant", root_path=settings.ROOT_PATH)
        self._watchdog = None
        self._jukuan_handler = None
        self.token = token if token else self.generate_token()
        self._db_session = db_session
        self._account_repository = account_repository
        self._signal_log_repository = signal_log_repository
        self.order_tracker = OrderTracker(repository=order_repository)
        self._poll_task: Optional[asyncio.Task] = None
        self._market_open_poll_task: Optional[asyncio.Task] = None
        self.running = False
        self.strategy_manager = StrategyManager(repository=strategy_repository)
        self.bark_service = BarkService(
            settings_repository, strategy_lookup=self._bark_strategy_gate
        )
        self.pending_buy_manager = PendingBuyManager(
            strategy_manager=self.strategy_manager,
            order_tracker=self.order_tracker,
            repository=pending_buy_repository,
            signal_log_repository=signal_log_repository,
            bark_service=self.bark_service,
            handler_factory=self._get_jukuan_handler,
            track_callback=self._track_and_apply_order,
        )
        self._register_order_state_callback()
        print(f"\n授权Token: {self.token}\n")

    def generate_token(self) -> str:
        secets_token = secrets.token_hex(32)
        return secets_token

    async def verify_token(self, x_token: str = Header(...)):
        return await _verify_token(x_token)

    async def verify_any_token(self, x_token: str = Header(...)):
        return await _verify_any_token(x_token)

    @property
    def trader(self):
        return self._watchdog.trader if self._watchdog is not None else None

    @property
    def account(self):
        return self._watchdog.account if self._watchdog is not None else None

    @property
    def callback(self):
        return self._watchdog.callback if self._watchdog is not None else None

    @property
    def qmt_connected(self) -> bool:
        return self._watchdog.connected if self._watchdog is not None else False

    @property
    def connection_state(self) -> str:
        return self._watchdog.state if self._watchdog is not None else ConnectionState.DISCONNECTED.value

    @property
    def last_connection_error(self) -> Optional[str]:
        return self._watchdog.last_error if self._watchdog is not None else None

    @property
    def reconnect_attempts(self) -> int:
        return self._watchdog.reconnect_attempts if self._watchdog is not None else 0

    async def init_trader_async(self):
        """异步初始化 trader，启动连接看门狗。"""
        self._watchdog = QMTConnectionWatchdog(
            account_id=self.account_id,
            qmt_path=self.mini_qmt_path,
            order_tracker=self.order_tracker,
        )
        await self._watchdog.start()

    def init_trader(self):
        """同步兼容入口，实际委托给 init_trader_async。

        注意：在已有运行事件循环的协程中应直接调用 init_trader_async。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.init_trader_async())
        else:
            raise RuntimeError("init_trader 为同步兼容方法，请在异步上下文中使用 init_trader_async")

    def _get_jukuan_handler(self):
        """返回绑定当前 trader/account 的聚宽下单处理器（连接重建后自动刷新）。"""
        current_trader = self.trader
        current_account = self.account
        handler = self._jukuan_handler
        if (
            handler is None
            or handler.trader is not current_trader
            or handler.account is not current_account
        ):
            self._jukuan_handler = JukuanOrderHandler(
                trader=current_trader,
                account=current_account,
                strategy_manager=self.strategy_manager,
            )
        return self._jukuan_handler

    def _defer_buy_if_applicable(self, strategy_id, method_name, stock_code,
                                 payload, signal_log, reason):
        """买入资金不足时按策略开关挂起买单。

        策略开启 defer_buy_on_insufficient_funds 且存在在途卖单时返回
        deferred 响应 dict；否则返回 None，调用方维持原有报错路径。
        """
        if not strategy_id:
            return None
        strategy = self.strategy_manager.get(strategy_id)
        if strategy is None or not getattr(strategy, 'defer_buy_on_insufficient_funds', False):
            return None
        if not self.pending_buy_manager.has_pending_sell_orders(strategy_id):
            return None
        pb = self.pending_buy_manager.defer(
            strategy_id=strategy_id,
            method_name=method_name,
            stock_code=stock_code,
            payload=payload,
            signal_log_id=signal_log.id if signal_log is not None else None,
            reason=reason,
        )
        if signal_log is not None and self._signal_log_repository is not None:
            self._signal_log_repository.update_error(
                signal_log.id, f"资金不足，已挂起等待卖出成交: {reason}"
            )
        return {
            'success': True,
            'data': {
                'order_id': None,
                'deferred': True,
                'pending_buy_id': pb.id,
                'message': (
                    f"资金不足，已挂起等待卖出成交"
                    f"（{settings.PENDING_BUY_EXPIRE_MINUTES} 分钟内自动重试）"
                ),
            },
        }

    def _register_order_state_callback(self):
        """注册订单状态变更回调，用于在终态时修正策略持仓并通知源平台。"""
        webhook_mapping = settings.SOURCE_PLATFORM_WEBHOOKS or {}

        def on_state_change(order):
            # 1) 策略持仓修正/回滚
            if order.strategy_id and order.optimistic_position_applied:
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

            # 2) 源平台状态通知（非阻塞，失败不影响状态机）
            if getattr(order, "notify_source", False):
                webhook_url = resolve_webhook_url(order, webhook_mapping)
                if webhook_url:
                    thread = threading.Thread(
                        target=notify_source_platform,
                        args=(order, webhook_url),
                        daemon=True,
                    )
                    thread.start()

            # 3) Bark 手机推送（非阻塞，内部自行判断开关）
            self.bark_service.notify_terminal(order)

        self.order_tracker.on_state_change(on_state_change)

        def on_fill_progress(order, delta_qty, delta_price):
            # 卖单部分成交：该笔回款立即计入策略可用资金（增量结算），
            # 挂起买单在卖单缓慢成交过程中即可逐步买入
            if (
                order.direction == 'sell'
                and order.strategy_id
                and order.optimistic_position_applied
                and order.optimistic_snapshot
            ):
                self.strategy_manager.settle_partial_sell(
                    order.strategy_id,
                    order.stock_code,
                    delta_qty,
                    delta_price,
                    order.optimistic_snapshot,
                )

        self.order_tracker.on_fill_progress(on_fill_progress)

    def _bark_strategy_gate(self, strategy_id: Optional[str]) -> bool:
        """Bark 策略级开关：无策略订单只看全局开关；策略已删除默认放行。"""
        if not strategy_id:
            return True
        strategy = self.strategy_manager.get(strategy_id)
        return strategy.bark_notify_enabled if strategy is not None else True

    def _track_and_apply_order(self, order_result: dict, strategy_id: Optional[str],
                               strategy_name: str, stock_name: str = "") -> Optional[TrackedOrder]:
        """将订单注册到跟踪器；乐观冻结已在下单前完成，这里仅传递快照。"""
        order_id = order_result.get('order_id')
        if not order_id:
            return None
        print(f"跟踪订单 {order_id}，策略: {strategy_name}, 策略ID: {strategy_id}")
        jq_code = order_result.get('jq_code', '')
        direction = order_result.get('direction', '')
        quantity = order_result.get('quantity', 0)
        price = order_result.get('price', 0.0)
        order_type = order_result.get('order_type', 0)
        qmt_code = order_result.get('qmt_code') or normalize_to_qmt(jq_code)

        snapshot = order_result.get('optimistic_snapshot')
        optimistic_applied = snapshot is not None

        notify_source = order_result.get('notify_source', False)
        source_platform_webhook = order_result.get('source_platform_webhook')
        source_platform = order_result.get('source_platform')

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
            price_type=order_result.get('price_type') or (FIX_PRICE if price > 0 else LATEST_PRICE),
            optimistic_position_applied=optimistic_applied,
            optimistic_snapshot=snapshot,
            notify_source=notify_source,
            source_platform_webhook=source_platform_webhook,
            source_platform=source_platform,
        )
        tracked = self.order_tracker.get_order(str(order_id))
        if tracked is not None:
            self.bark_service.notify_placed(tracked)
        return tracked

    async def _poll_orders_loop(self):
        """后台轮询 pending 订单状态，补偿漏掉的回调。仅在 QMT 连接正常时执行。"""
        try:
            while self.running:
                try:
                    if (
                        self._watchdog is not None
                        and self._watchdog.connected
                        and self.trader is not None
                        and self.account is not None
                    ):
                        # 同步 QMT 查询必须卸载到线程池并加超时，
                        # 否则 QMT 无响应时会冻结整个事件循环
                        await run_blocking(
                            self.order_tracker.poll_and_reconcile,
                            self.trader, self.account,
                            timeout=BLOCKING_CALL_TIMEOUT_LONG,
                        )
                        # 卖单对账入账后重试挂起买单（含过期清理），顺序不能颠倒
                        await run_blocking(
                            self.pending_buy_manager.process_all,
                            self.trader, self.account,
                            timeout=BLOCKING_CALL_TIMEOUT_LONG,
                        )
                        self.bark_service.check_stale_orders(
                            self.order_tracker.get_pending_orders()
                        )
                except Exception:
                    # 轮询失败不应影响主服务
                    pass
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    async def _market_open_poll_loop(self):
        """每天早上开盘时主动发起一次订单状态刷新。"""
        try:
            while self.running:
                delay = seconds_until_market_open()
                await asyncio.sleep(delay)
                if not self.running:
                    break
                if not (
                    self._watchdog is not None
                    and self._watchdog.connected
                    and self.trader is not None
                    and self.account is not None
                ):
                    continue
                try:
                    await run_blocking(
                        self.order_tracker.poll_and_reconcile,
                        self.trader, self.account,
                        timeout=BLOCKING_CALL_TIMEOUT_LONG,
                    )
                except Exception as e:
                    # 开盘轮询失败不应影响主服务
                    pass
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
            qmt_positions_raw = qmt_call(
                self.trader,
                "query_stock_positions",
                self.account,
                context={"account_id": getattr(self.account, 'account_id', self.account)},
            )
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

        async def endpoint(request: RequestModel, token: str = Depends(_require_qmt_connected)):
            try:
                params = request.dict(exclude_unset=True)
                if 'account' in param_names:
                    params['account'] = _current_server.account
                result = await run_blocking(
                    qmt_call,
                    _current_server.trader,
                    method_name,
                    context={"endpoint": f"/api/{method_name}", "params": params},
                    **params,
                )
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
            if _current_server is None:
                return {
                    'success': True,
                    'data': {
                        'running': False,
                        'qmt_connected': False,
                        'connection_state': ConnectionState.DISCONNECTED.value,
                        'last_connection_error': None,
                        'reconnect_attempts': 0,
                        'account_id': None,
                        'qmt_path': None,
                        'host': None,
                        'port': None,
                    }
                }
            return {
                'success': True,
                'data': {
                    'running': _current_server.running,
                    'qmt_connected': _current_server.qmt_connected,
                    'connection_state': _current_server.connection_state,
                    'last_connection_error': _current_server.last_connection_error,
                    'reconnect_attempts': _current_server.reconnect_attempts,
                    'account_id': _current_server.account_id,
                    'qmt_path': _current_server.mini_qmt_path,
                    'host': _current_server.host,
                    'port': _current_server.port,
                }
            }

        @app.get('/api/test-connection')
        async def test_connection(token: str = Depends(_require_qmt_connected)):
            try:
                result = await run_blocking(
                    qmt_call,
                    _current_server.trader,
                    "query_stock_asset",
                    _current_server.account,
                    context={"account_id": getattr(_current_server.account, 'account_id', _current_server.account)},
                )
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
                    "price_type": o.price_type,
                    "status": o.status,
                    "order_type": o.order_type,
                    "strategy_id": o.strategy_id,
                    "strategy_name": o.strategy_name,
                    "placed_at": o.placed_at.isoformat() if o.placed_at else None,
                    "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
                    "error_msg": o.error_msg,
                    "retried_as_order_id": o.retried_as_order_id,
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

        @app.post('/api/orders/{order_id}/cancel')
        async def cancel_order(
            order_id: str = Path(...),
            token: str = Depends(_require_qmt_connected),
        ):
            try:
                order = await run_blocking(
                    _current_server.order_tracker.cancel_order,
                    _current_server.trader, _current_server.account, order_id,
                )
                return {'success': True, 'data': {
                    "order_id": order.order_id,
                    "status": order.status,
                    "error_msg": order.error_msg,
                }}
            except ValueError as e:
                status_code = 404 if "不存在" in str(e) else 400
                raise HTTPException(status_code=status_code, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"撤销失败: {e}")

        @app.post('/api/orders/{order_id}/resend')
        async def resend_order(
            order_id: str = Path(...),
            data: Optional[OrderResendRequest] = None,
            token: str = Depends(_require_qmt_connected),
        ):
            order = _current_server.order_tracker.get_order(order_id)
            if order is None:
                raise HTTPException(status_code=404, detail="订单不存在")
            if order.status != OrderState.FAILED:
                raise HTTPException(status_code=400, detail="仅失败订单可重发")
            if order.retried_as_order_id is not None:
                raise HTTPException(status_code=400, detail="订单已重发过")

            # 合并可选的覆盖参数；price=0 是合法的市价显式值，必须用 is not None 判断
            new_quantity = data.quantity if data and data.quantity is not None else order.quantity
            new_price = data.price if data and data.price is not None else order.price
            # 报价方式：显式传入优先；仅传 price 时保持按价推导的旧行为；空请求体沿用原单报价方式
            if data and data.price_type is not None:
                new_price_type = data.price_type
            elif data and data.price is not None:
                new_price_type = None
            else:
                new_price_type = order.price_type

            # 人工重发时买入须为整手（股票 100 股、可转债 10 张；期货除外）；卖出允许零股，故不校验
            if (order.direction == 'buy'
                    and not is_future(order.stock_code)
                    and new_quantity % get_lot_size(order.stock_code) != 0):
                raise HTTPException(
                    status_code=400,
                    detail=f"买入数量须为{get_lot_size(order.stock_code)}的整数倍（{get_quantity_unit(order.stock_code)}）",
                )

            handler = _get_jukuan_handler()
            try:
                result = await run_blocking(
                    handler._submit_order,
                    order.stock_code,
                    order.order_type,
                    new_quantity,
                    price=new_price,
                    price_type=new_price_type,
                    strategy_name=order.strategy_name,
                    strategy_id=order.strategy_id,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"重发失败: {e}")

            order_result = {
                'order_id': result['order_id'],
                'jq_code': order.jq_code,
                'direction': order.direction,
                'quantity': new_quantity,
                'price': new_price,
                'price_type': result.get('price_type'),
                'order_type': order.order_type,
                'optimistic_snapshot': result['optimistic_snapshot'],
            }
            new_order = _current_server._track_and_apply_order(
                order_result, order.strategy_id, order.strategy_name, stock_name=order.stock_name
            )
            if new_order is None:
                raise HTTPException(status_code=500, detail="重发后跟踪订单失败")

            order.retried_as_order_id = new_order.order_id
            _current_server.order_tracker._persist(order, None, "resend")

            return {'success': True, 'data': {
                "order_id": new_order.order_id,
                "stock_code": new_order.stock_code,
                "direction": new_order.direction,
                "quantity": new_order.quantity,
                "price": new_order.price,
                "price_type": new_order.price_type,
                "status": new_order.status,
                "retried_from_order_id": order.order_id,
            }}

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
        async def account_asset(token: str = Depends(_require_qmt_connected)):
            try:
                result = await run_blocking(
                    qmt_call,
                    _current_server.trader,
                    "query_stock_asset",
                    _current_server.account,
                    context={"account_id": getattr(_current_server.account, 'account_id', _current_server.account)},
                )
                converted_result = _current_server.convert_to_dict(result)

                positions = await run_blocking(
                    _current_server._query_account_positions,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
                daily_profit = round(sum(p.get('daily_pnl', 0) for p in positions), 2)

                converted_result['daily_profit'] = daily_profit
                converted_result['positions'] = positions
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get('/api/account-positions')
        async def account_positions(token: str = Depends(_require_qmt_connected)):
            try:
                positions = await run_blocking(
                    _current_server._query_account_positions,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
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

        def _check_qmt_connected():
            """在内部端点中检查 QMT 连接状态，未连接时抛出 503。"""
            if _current_server is None or not _current_server.running:
                raise HTTPException(status_code=503, detail="服务未启动")
            if not _current_server.qmt_connected:
                detail = "QMT 连接断开，正在重连"
                if _current_server.last_connection_error:
                    detail += f": {_current_server.last_connection_error}"
                raise HTTPException(status_code=503, detail=detail)

        def _get_jukuan_handler():
            return _current_server._get_jukuan_handler()

        async def _jukuan_endpoint(request: dict, x_token: str, method_name: str,
                                   raw_request: Optional[Request] = None):
            _check_qmt_connected()
            strategy_name, strategy_id = _resolve_strategy(request, x_token)
            if strategy_id is None:
                raise HTTPException(status_code=403, detail="聚宽下单接口仅支持策略Token")
            handler = _get_jukuan_handler()

            security = request.get('security', '').strip()
            if not security:
                raise HTTPException(status_code=400, detail="请提供 security 参数")

            client_ip = _get_client_ip(raw_request)

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

                name_map = await run_blocking(
                    fetch_stock_names_from_xtdata, {qmt_code},
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
                stock_name = name_map.get(qmt_code) or ""

                amount = request.get('amount', 0)
                value = request.get('value', 0)
                side = request.get('side', 'long')

                method = getattr(handler, method_name)
                try:
                    if method_name in ('jukuan_order', 'jukuan_order_target'):
                        result = await run_blocking(
                            method, qmt_code, amount,
                            side=side, strategy_id=strategy_id,
                            timeout=BLOCKING_CALL_TIMEOUT_LONG,
                        )
                    else:
                        result = await run_blocking(
                            method, qmt_code, value,
                            side=side, strategy_id=strategy_id,
                            timeout=BLOCKING_CALL_TIMEOUT_LONG,
                        )
                except InsufficientFundsError as e:
                    # 策略开启延迟买单且存在在途卖单时，挂起等待卖出成交
                    deferred = _current_server._defer_buy_if_applicable(
                        strategy_id, method_name, qmt_code, request, signal_log, str(e)
                    )
                    if deferred is not None:
                        return deferred
                    raise

                # max_buyable 策略资金不足一手被取消时，同样可挂起等待卖出成交
                if not result.get('order_id') and result.get('funds_cap_note'):
                    deferred = _current_server._defer_buy_if_applicable(
                        strategy_id, method_name, qmt_code, request, signal_log,
                        result['funds_cap_note'],
                    )
                    if deferred is not None:
                        return deferred

                # 保留原始聚宽代码便于返回和日志
                result['jq_code'] = security

                # 透传源平台通知开关与回调地址
                result['notify_source'] = request.get('notify_source', False)
                result['source_platform_webhook'] = request.get('source_platform_webhook')
                result['source_platform'] = request.get('source_platform')

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
                    # max_buyable 策略资金不足被封顶/取消时，信号日志记为异常并注明部分下单情况
                    funds_cap_note = result.get('funds_cap_note')
                    if funds_cap_note:
                        _current_server._signal_log_repository.update_error(
                            signal_log.id, funds_cap_note
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

        @app.post('/api/order')
        async def generic_order_endpoint(
            data: GenericOrderRequest,
            raw_request: Request,
            x_token: str = Header(...),
        ):
            """通用下单接口（策略 Token），支持业务层全参数下单。"""
            _check_qmt_connected()
            strategy_name, strategy_id = _resolve_strategy(data.model_dump(), x_token)
            if strategy_id is None:
                raise HTTPException(status_code=403, detail="通用下单接口仅支持策略Token")

            qmt_code = normalize_to_qmt(data.security)
            if not qmt_code:
                raise HTTPException(status_code=400, detail="请提供有效的 security 参数")

            client_ip = _get_client_ip(raw_request)

            signal_log = None
            if _current_server._signal_log_repository is not None:
                signal_log = _current_server._signal_log_repository.add(
                    SignalLogModel(
                        strategy_id=strategy_id,
                        endpoint="/api/order",
                        source_platform=data.source_platform,
                        source_ip=client_ip,
                        payload=data.model_dump(),
                        received_at=datetime.now(timezone.utc),
                        created_at=datetime.now(timezone.utc),
                    )
                )

            try:
                if data.order_type is not None and data.order_type not in ORDER_TYPE_SET:
                    raise ValueError(f"不支持的 order_type: {data.order_type}")
                if data.price_type is not None and data.price_type not in PRICE_TYPE_SET:
                    raise ValueError(f"不支持的 price_type: {data.price_type}")

                name_map = await run_blocking(
                    fetch_stock_names_from_xtdata, {qmt_code},
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
                stock_name = name_map.get(qmt_code) or ""

                handler = _get_jukuan_handler()
                try:
                    result = await run_blocking(
                        handler.generic_order,
                        stock_code=qmt_code,
                        quantity=data.quantity,
                        direction=data.direction,
                        price=data.price,
                        price_type=data.price_type,
                        order_type=data.order_type,
                        strategy_name=strategy_name or data.strategy_name,
                        strategy_id=strategy_id,
                        order_remark=data.order_remark,
                        timeout=BLOCKING_CALL_TIMEOUT_LONG,
                    )
                except InsufficientFundsError as e:
                    # 策略开启延迟买单且存在在途卖单时，挂起等待卖出成交
                    deferred = _current_server._defer_buy_if_applicable(
                        strategy_id, 'generic_order', qmt_code,
                        data.model_dump(), signal_log, str(e),
                    )
                    if deferred is not None:
                        return deferred
                    raise

                # max_buyable 策略资金不足一手被取消时，同样可挂起等待卖出成交
                if not result.get('order_id') and result.get('funds_cap_note'):
                    deferred = _current_server._defer_buy_if_applicable(
                        strategy_id, 'generic_order', qmt_code,
                        data.model_dump(), signal_log, result['funds_cap_note'],
                    )
                    if deferred is not None:
                        return deferred

                # 注册订单到跟踪器，并对策略持仓进行乐观更新
                if result.get('order_id'):
                    result['strategy_name'] = strategy_name or data.strategy_name
                    result['notify_source'] = data.notify_source
                    result['source_platform_webhook'] = data.source_platform_webhook
                    result['source_platform'] = data.source_platform
                    _current_server._track_and_apply_order(
                        result, strategy_id, strategy_name or data.strategy_name, stock_name=stock_name
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
                        'method': 'generic_order',
                    })

                if signal_log is not None and _current_server._signal_log_repository is not None:
                    order_id = str(result.get('order_id', '')) if result.get('order_id') else None
                    _current_server._signal_log_repository.update_processed_order(
                        signal_log.id, order_id
                    )
                    # max_buyable 策略资金不足被封顶/取消时，信号日志记为异常并注明部分下单情况
                    funds_cap_note = result.get('funds_cap_note')
                    if funds_cap_note:
                        _current_server._signal_log_repository.update_error(
                            signal_log.id, funds_cap_note
                        )

                return {'success': True, 'data': result}
            except ValueError as e:
                if signal_log is not None and _current_server._signal_log_repository is not None:
                    _current_server._signal_log_repository.update_error(signal_log.id, str(e))
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                if signal_log is not None and _current_server._signal_log_repository is not None:
                    _current_server._signal_log_repository.update_error(signal_log.id, str(e))
                raise HTTPException(status_code=500, detail=f"下单失败: {e}")

        @app.get('/api/strategy_info')
        async def strategy_info(strategy=Depends(_verify_strategy_token)):
            """外部服务用策略 Token 查询本策略的基本信息与资金汇总。"""
            enriched = await run_blocking(
                _current_server.strategy_manager.list_all_enriched,
                _current_server.trader, _current_server.account,
                timeout=BLOCKING_CALL_TIMEOUT_LONG,
            )
            data = next((s for s in enriched if s['id'] == strategy.id), None)
            if data is None:
                raise HTTPException(status_code=404, detail="策略不存在")
            # 白名单返回，不暴露 token、持仓明细、交易记录等内部字段
            return {'success': True, 'data': {
                'id': data['id'],
                'name': data['name'],
                'description': data['description'],
                'enabled': data['enabled'],
                'security_type': data['security_type'],
                'allocated_funds': data['allocated_funds'],
                'available_cash': data['available_cash'],
                'total_asset': data['total_asset'],
                'daily_pnl': data['daily_pnl'],
            }}

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
            strategies = await run_blocking(
                _current_server.strategy_manager.list_all_enriched,
                _current_server.trader, _current_server.account,
                timeout=BLOCKING_CALL_TIMEOUT_LONG,
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
                strategy = await run_blocking(
                    _current_server.strategy_manager.create, data,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
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
                strategy = await run_blocking(
                    _current_server.strategy_manager.update, strategy_id, data,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
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
            deleted = await run_blocking(
                _current_server.strategy_manager.delete, strategy_id
            )
            if not deleted:
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': {'message': '策略已删除'}}

        @app.post('/api/strategies/{strategy_id}/toggle')
        async def toggle_strategy(
            strategy_id: str = Path(...),
            token: str = Depends(_verify_token),
        ):
            strategy = await run_blocking(
                _current_server.strategy_manager.toggle, strategy_id
            )
            if not strategy:
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': strategy.model_dump()}

        @app.post('/api/strategies/{strategy_id}/order')
        async def place_strategy_order(
            strategy_id: str = Path(...),
            data: ManualOrderRequest = ...,
            token: str = Depends(_require_qmt_connected),
        ):
            """Web UI 手动下单（主 Token），复用聚宽下单的冻结/校验/跟踪链路。"""
            strategy = _current_server.strategy_manager.get(strategy_id)
            if strategy is None:
                raise HTTPException(status_code=404, detail="策略不存在")
            if not strategy.enabled:
                raise HTTPException(status_code=400, detail="策略已禁用，无法下单")
            if data.direction not in ('buy', 'sell'):
                raise HTTPException(status_code=400, detail="direction 必须为 buy 或 sell")

            qmt_code = normalize_to_qmt(data.stock_code.strip())
            if not qmt_code:
                raise HTTPException(status_code=400, detail="请提供股票代码")

            # 买入须为整手（股票 100 股、可转债 10 张；期货除外），与重发端点规则一致；卖出允许零股
            if (data.direction == 'buy'
                    and not is_future(qmt_code)
                    and data.quantity % get_lot_size(qmt_code) != 0):
                raise HTTPException(
                    status_code=400,
                    detail=f"买入数量须为{get_lot_size(qmt_code)}的整数倍（{get_quantity_unit(qmt_code)}）",
                )

            stock_name = (await run_blocking(
                fetch_stock_names_from_xtdata, {qmt_code},
                timeout=BLOCKING_CALL_TIMEOUT_LONG,
            )).get(qmt_code) or ""
            order_type = STOCK_BUY if data.direction == 'buy' else STOCK_SELL

            handler = _get_jukuan_handler()
            try:
                result = await run_blocking(
                    handler._submit_order,
                    qmt_code,
                    order_type,
                    data.quantity,
                    price=data.price,
                    price_type=data.price_type,
                    strategy_name=strategy.name,
                    strategy_id=strategy.id,
                    timeout=BLOCKING_CALL_TIMEOUT_LONG,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"下单失败: {e}")

            # 策略配置为 max_buyable 且可用资金不足一手时，_submit_order 返回订单取消
            if not result.get('order_id'):
                raise HTTPException(
                    status_code=400,
                    detail=result.get('message', '策略可用资金不足，订单取消'),
                )

            actual_quantity = result.get('quantity', data.quantity)
            order_result = {
                'order_id': result['order_id'],
                'jq_code': qmt_to_jq(qmt_code),
                'direction': data.direction,
                'quantity': actual_quantity,
                'price': data.price,
                'price_type': result.get('price_type'),
                'order_type': order_type,
                'optimistic_snapshot': result['optimistic_snapshot'],
                'notify_source': data.notify_source,
                'source_platform_webhook': data.source_platform_webhook,
                'source_platform': data.source_platform,
            }
            new_order = _current_server._track_and_apply_order(
                order_result, strategy.id, strategy.name, stock_name=stock_name
            )
            if new_order is None:
                raise HTTPException(status_code=500, detail="下单后跟踪订单失败")

            _current_server.strategy_manager.add_trading_record(strategy.id, {
                'timestamp': datetime.now().isoformat(),
                'stock_code': qmt_code,
                'direction': data.direction,
                'quantity': actual_quantity,
                'price': data.price,
                'order_id': str(result['order_id']),
                'method': 'manual_order',
            })

            return {'success': True, 'data': {
                "order_id": new_order.order_id,
                "stock_code": new_order.stock_code,
                "stock_name": new_order.stock_name,
                "jq_code": new_order.jq_code,
                "direction": new_order.direction,
                "quantity": new_order.quantity,
                "price": new_order.price,
                "price_type": new_order.price_type,
                "status": new_order.status,
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
            }}

        @app.post('/api/strategies/refresh')
        async def refresh_strategies(token: str = Depends(_require_qmt_connected)):
            strategies = await run_blocking(
                _current_server.strategy_manager.list_all_enriched,
                _current_server.trader, _current_server.account,
                timeout=BLOCKING_CALL_TIMEOUT_LONG,
            )
            return {'success': True, 'data': _enrich_order_count(strategies)}

        @app.get('/api/bark-config')
        async def get_bark_config(token: str = Depends(_verify_token)):
            return {'success': True, 'data': _current_server.bark_service.get_config().model_dump()}

        @app.put('/api/bark-config')
        async def update_bark_config(data: BarkConfig, token: str = Depends(_verify_token)):
            saved = _current_server.bark_service.update_config(data)
            return {'success': True, 'data': saved.model_dump()}

        @app.post('/api/bark-config/test')
        async def test_bark_config(data: BarkConfig = None, token: str = Depends(_verify_token)):
            """发送一条测试推送验证绑定；body 可选，可用表单未保存的值先试。"""
            ok = await asyncio.to_thread(_current_server.bark_service.send_test, data)
            if not ok:
                raise HTTPException(status_code=502, detail="推送失败，请检查 Key 与服务器地址")
            return {'success': True, 'data': {'message': '测试推送已发送，请查看手机'}}

    def init_and_setup(self, target_app=None):
        """同步兼容入口，实际委托给 init_and_setup_async。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.init_and_setup_async(target_app=target_app))
        else:
            raise RuntimeError(
                "init_and_setup 为同步兼容方法，请在异步上下文中使用 init_and_setup_async"
            )

    async def init_and_setup_async(self, target_app=None):
        """异步初始化：建立 QMT 连接、加载订单、注册路由、启动后台轮询。"""
        try:
            self._ensure_account_record()
            await self.init_trader_async()
        except Exception:
            self.setup_routes(target_app=target_app)
            raise

        # 等待首次连接建立，最多 10 秒
        for _ in range(200):
            if self.qmt_connected:
                break
            await asyncio.sleep(0.05)

        self.order_tracker._load_orders()
        self._bump_mock_order_counter()
        self.setup_routes(target_app=target_app)
        self.running = True
        self._poll_task = asyncio.create_task(self._poll_orders_loop())
        self._market_open_poll_task = asyncio.create_task(self._market_open_poll_loop())

    def _bump_mock_order_counter(self):
        """将 MockTrader 的订单号计数器抬升到历史最大订单号之上。

        MockTrader 的计数器是类属性，每次进程启动都从 100000 重新计数；
        若数据库中已存在历史 mock 订单号，新订单号冲突会覆盖内存与数据库中的
        旧订单。真实 XtQuantTrader 没有该方法，getattr 返回 None 自动跳过。
        """
        bump = getattr(self.trader, 'bump_order_counter', None)
        if not callable(bump):
            return
        numeric_ids = [
            int(o.order_id) for o in self.order_tracker.list_all()
            if str(o.order_id).isdigit()
        ]
        if numeric_ids:
            bump(max(numeric_ids))

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
        """同步停止入口，会自动选择合适方式执行异步清理。"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            asyncio.run(self.stop_async())
            return
        if loop.is_running():
            loop.create_task(self.stop_async())
        else:
            loop.run_until_complete(self.stop_async())

    async def stop_async(self):
        """异步停止：取消轮询任务、停止看门狗、关闭数据库会话。"""
        global _current_server
        self.running = False
        for task_attr in ('_poll_task', '_market_open_poll_task'):
            task = getattr(self, task_attr, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, task_attr, None)
        if self._watchdog is not None:
            await self._watchdog.stop()
            self._watchdog = None
        if self._db_session is not None:
            self._db_session.close()
            self._db_session = None
        _current_server = None


def create_server(account_id: str, mini_qmt_path: str,
                  host: str = settings.SERVER_HOST, port: int = settings.SERVER_PORT, token: str = None):
    return QMTServer(account_id, mini_qmt_path, host, port, token)
