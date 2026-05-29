from typing import Optional, Literal
from pydantic import BaseModel
from collections import deque
from datetime import datetime

from backend.qmt_client import jq_to_qmt
from backend.logger import logger
from backend.constants import GREEN, BLUE, RESET, STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import FIX_PRICE, LATEST_PRICE


class TradeSignal(BaseModel):
    signal_id: str
    stock_code: str
    direction: Literal["buy", "sell"]
    quantity: int
    price: Optional[float] = None
    order_type: str = "limit"
    strategy_name: Optional[str] = None
    timestamp: Optional[str] = None


class SignalReceiver:
    def __init__(self, trader, account, callback, signal_log: deque, wechat_webhook: str = None):
        self.trader = trader
        self.account = account
        self.callback = callback
        self.signal_log = signal_log
        self.wechat_webhook = wechat_webhook

    async def receive_signal(self, signal: TradeSignal) -> dict:
        qmt_code = jq_to_qmt(signal.stock_code)

        order_type = STOCK_BUY if signal.direction == "buy" else STOCK_SELL

        price = signal.price if signal.price is not None else 0
        strategy = signal.strategy_name or "remote_signal"

        try:
            price_type = FIX_PRICE if price > 0 else LATEST_PRICE

            order_id = self.trader.order_stock(
                self.account,
                stock_code=qmt_code,
                order_type=order_type,
                order_volume=signal.quantity,
                price_type=price_type,
                price=price,
                strategy_name=strategy,
                order_remark=signal.stock_code
            )

            signal_entry = {
                "type": "signal",
                "signal_id": signal.signal_id,
                "stock_code": signal.stock_code,
                "qmt_code": qmt_code,
                "direction": signal.direction,
                "quantity": signal.quantity,
                "price": price,
                "order_type": signal.order_type,
                "strategy_name": strategy,
                "order_id": str(order_id),
                "status": "submitted",
                "timestamp": signal.timestamp or datetime.now().isoformat(),
                "message": f"信号执行: {signal.direction} {signal.stock_code} {signal.quantity}股",
            }

            self.signal_log.append(signal_entry)

            logger.info(
                f"{BLUE}【远程信号】{RESET} "
                f"信号ID:{signal.signal_id} "
                f"股票:{signal.stock_code}→{qmt_code} "
                f"方向:{signal.direction} "
                f"数量:{signal.quantity} "
                f"价格:{price if price else '市价'} "
                f"订单编号:{order_id}"
            )

            return {
                "success": True,
                "data": {
                    "order_id": order_id,
                    "signal_id": signal.signal_id,
                    "qmt_code": qmt_code,
                }
            }

        except Exception as e:
            error_entry = {
                "type": "signal_error",
                "signal_id": signal.signal_id,
                "stock_code": signal.stock_code,
                "direction": signal.direction,
                "quantity": signal.quantity,
                "status": "failed",
                "timestamp": signal.timestamp or datetime.now().isoformat(),
                "message": f"信号执行失败: {str(e)}",
            }
            self.signal_log.append(error_entry)
            logger.error(f"信号执行失败: {signal.signal_id} - {str(e)}")
            raise
