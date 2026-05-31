from fastapi import FastAPI, HTTPException, Header, Depends, Path
from pydantic import BaseModel
import inspect
import secrets
from typing import Any, Optional
from collections import deque
from backend.qmt_client import create_trader
from backend.strategy_manager import StrategyManager, StrategyCreate, StrategyUpdate
import uvicorn


class QMTServer:
    def __init__(self, account_id: str, mini_qmt_path: str,
                 host: str = "0.0.0.0", port: int = 8000, token: str = None):
        self.account_id = account_id
        self.mini_qmt_path = mini_qmt_path
        self.host = host
        self.port = port
        self.app = FastAPI(title="QMT Live Assistant")
        self.trader = None
        self.account = None
        self.callback = None
        self.token = token if token else self.generate_token()
        self.signal_log = deque(maxlen=200)
        self._signal_receiver = None
        self.running = False
        self.strategy_manager = StrategyManager()
        print(f"\n授权Token: {self.token}\n")

    def generate_token(self) -> str:
        secets_token = secrets.token_hex(32)
        print("生成新的授权Token: " + secets_token)
        return secets_token

    async def verify_token(self, x_token: str = Header(...)):
        if x_token != self.token:
            raise HTTPException(status_code=401, detail="无效的Token")
        return x_token

    async def verify_any_token(self, x_token: str = Header(...)):
        if x_token == self.token:
            return x_token
        strategy = self.strategy_manager.find_by_token(x_token)
        if strategy and strategy.enabled:
            return x_token
        raise HTTPException(status_code=401, detail="无效的Token")

    def init_trader(self):
        self.trader, self.account, self.callback = create_trader(
            self.account_id, self.mini_qmt_path, signal_log=self.signal_log
        )

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

        async def endpoint(request: RequestModel, token: str = Depends(self.verify_token)):
            try:
                params = request.dict(exclude_unset=True)
                if 'account' in param_names:
                    params['account'] = self.account
                result = getattr(self.trader, method_name)(**params)
                converted_result = self.convert_to_dict(result)
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
                    'running': self.running,
                    'account_id': self.account_id,
                    'qmt_path': self.mini_qmt_path,
                    'host': self.host,
                    'port': self.port,
                }
            }

        @app.get('/api/test-connection')
        async def test_connection(token: str = Depends(self.verify_token)):
            try:
                if self.trader is None:
                    self.init_trader()
                result = self.trader.query_stock_asset(self.account)
                converted_result = self.convert_to_dict(result)
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"连接测试失败: {str(e)}")

        @app.get('/api/signals')
        async def get_signals(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            strategy_name: Optional[str] = None,
            token: str = Depends(self.verify_token),
        ):
            signals = list(self.signal_log)
            if strategy_name:
                signals = [s for s in signals if s.get('strategy_name') == strategy_name]
            if start_date:
                signals = [s for s in signals if s.get('timestamp', '')[:10] >= start_date]
            if end_date:
                signals = [s for s in signals if s.get('timestamp', '')[:10] <= end_date]
            return {'success': True, 'data': signals}

        @app.get('/api/account-asset')
        async def account_asset(token: str = Depends(self.verify_token)):
            try:
                result = self.trader.query_stock_asset(self.account)
                converted_result = self.convert_to_dict(result)
                return {'success': True, 'data': converted_result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post('/api/convert/jq-to-qmt')
        async def convert_jq_to_qmt(request: dict):
            from backend.qmt_client import jq_to_qmt
            code = request.get('code', '')
            return {'success': True, 'data': {'result': jq_to_qmt(code)}}

        @app.post('/api/convert/qmt-to-jq')
        async def convert_qmt_to_jq(request: dict):
            from backend.qmt_client import qmt_to_jq
            code = request.get('code', '')
            return {'success': True, 'data': {'result': qmt_to_jq(code)}}

        @app.post('/api/receive-signal')
        async def receive_signal_endpoint(request: dict, x_token: str = Header(...)):
            from backend.signal_handler import TradeSignal, SignalReceiver

            # 验证 token（同时支持主 token 和策略 token）
            if x_token != self.token:
                strategy = self.strategy_manager.find_by_token(x_token)
                if not strategy or not strategy.enabled:
                    raise HTTPException(status_code=401, detail="无效的Token")
                request['strategy_name'] = strategy.name
                request['_strategy_id'] = strategy.id

            if self._signal_receiver is None:
                self._signal_receiver = SignalReceiver(
                    trader=self.trader,
                    account=self.account,
                    callback=self.callback,
                    signal_log=self.signal_log,
                    strategy_manager=self.strategy_manager,
                )

            signal = TradeSignal(**{k: v for k, v in request.items() if not k.startswith('_')})
            strategy_id = request.get('_strategy_id')
            try:
                result = await self._signal_receiver.receive_signal(signal)

                # 信号执行成功后更新策略持仓和记录
                if strategy_id:
                    price = signal.price if signal.price is not None and signal.price > 0 else 0
                    self.strategy_manager.update_position(
                        strategy_id, signal.stock_code,
                        signal.direction, signal.quantity, price
                    )
                    self.strategy_manager.increment_signal_count(strategy_id)
                    self.strategy_manager.add_trading_record(strategy_id, {
                        "timestamp": signal.timestamp or "",
                        "stock_code": signal.stock_code,
                        "direction": signal.direction,
                        "quantity": signal.quantity,
                        "price": price,
                        "order_id": str(result.get("data", {}).get("order_id", "")),
                        "signal_id": signal.signal_id,
                    })

                return result
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # --- 策略管理 API ---

        @app.get('/api/strategies')
        async def list_strategies(token: str = Depends(self.verify_token)):
            return {'success': True, 'data': self.strategy_manager.list_all()}

        @app.post('/api/strategies')
        async def create_strategy(data: StrategyCreate, token: str = Depends(self.verify_token)):
            strategy = self.strategy_manager.create(data)
            return {'success': True, 'data': strategy.model_dump()}

        @app.put('/api/strategies/{strategy_id}')
        async def update_strategy(
            strategy_id: str = Path(...),
            data: StrategyUpdate = None,
            token: str = Depends(self.verify_token),
        ):
            strategy = self.strategy_manager.update(strategy_id, data)
            if not strategy:
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': strategy.model_dump()}

        @app.delete('/api/strategies/{strategy_id}')
        async def delete_strategy(
            strategy_id: str = Path(...),
            token: str = Depends(self.verify_token),
        ):
            if not self.strategy_manager.delete(strategy_id):
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': {'message': '策略已删除'}}

        @app.post('/api/strategies/{strategy_id}/toggle')
        async def toggle_strategy(
            strategy_id: str = Path(...),
            token: str = Depends(self.verify_token),
        ):
            strategy = self.strategy_manager.toggle(strategy_id)
            if not strategy:
                raise HTTPException(status_code=404, detail="策略不存在")
            return {'success': True, 'data': strategy.model_dump()}

        @app.post('/api/strategies/refresh')
        async def refresh_strategies(token: str = Depends(self.verify_token)):
            self.strategy_manager.refresh_from_qmt(self.trader, self.account)
            return {'success': True, 'data': self.strategy_manager.list_all()}

    def init_and_setup(self, target_app=None):
        self.init_trader()
        self.setup_routes(target_app=target_app)
        self.running = True

    def run(self):
        self.init_and_setup()
        uvicorn.run(self.app, host=self.host, port=self.port)

    def stop(self):
        self.running = False


def create_server(account_id: str, mini_qmt_path: str,
                  host: str = "0.0.0.0", port: int = 8000, token: str = None):
    return QMTServer(account_id, mini_qmt_path, host, port, token)
