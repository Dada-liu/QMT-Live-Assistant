import sys
import random
from collections import deque

from backend.utils import timestamp_to_datetime_string, parse_order_type, convert_to_current_date
from backend.constants import RED, GREEN, YELLOW, BLUE, RESET
from backend.logger import logger

error_orders = []


class MyXtQuantTraderCallback:
    def __init__(self, signal_log: deque = None):
        self.signal_log = signal_log

    def on_disconnected(self):
        logger.warning(f"{YELLOW}【连接断开】{RESET}")
        if self.signal_log is not None:
            self.signal_log.append({
                "type": "connection",
                "event": "disconnected",
                "message": "miniQMT 连接断开",
            })

    def on_stock_order(self, order):
        if order.order_status == 50:
            logger.info(
                f"{BLUE}【已委托】{RESET} {parse_order_type(order.order_type)} "
                f"代码:{order.stock_code} 名称:{order.order_remark} "
                f"委托价格:{order.price:.2f} 委托数量:{order.order_volume} "
                f"订单编号:{order.order_id} "
                f"委托时间:{timestamp_to_datetime_string(convert_to_current_date(order.order_time))}"
            )
        elif order.order_status in (53, 54):
            logger.warning(
                f"{YELLOW}【已撤单】{RESET} {parse_order_type(order.order_type)} "
                f"代码:{order.stock_code} 名称:{order.order_remark} "
                f"委托价格:{order.price:.2f} 委托数量:{order.order_volume} "
                f"订单编号:{order.order_id}"
            )
        if self.signal_log is not None:
            self.signal_log.append({
                "type": "order",
                "order_id": str(order.order_id),
                "stock_code": order.stock_code,
                "order_type": parse_order_type(order.order_type),
                "price": order.price,
                "volume": order.order_volume,
                "status": order.order_status,
                "message": f"{parse_order_type(order.order_type)} {order.stock_code} {order.order_volume}股",
            })

    def on_stock_trade(self, trade):
        logger.info(
            f"{GREEN}【已成交】{RESET} {parse_order_type(trade.order_type)} "
            f"代码:{trade.stock_code} 名称:{trade.order_remark} "
            f"成交价格:{trade.traded_price:.2f} 成交数量:{trade.traded_volume} "
            f"成交编号:{trade.order_id} "
            f"成交时间:{timestamp_to_datetime_string(convert_to_current_date(trade.traded_time))}"
        )
        if self.signal_log is not None:
            self.signal_log.append({
                "type": "trade",
                "order_id": str(trade.order_id),
                "stock_code": trade.stock_code,
                "order_type": parse_order_type(trade.order_type),
                "price": trade.traded_price,
                "volume": trade.traded_volume,
                "status": "filled",
                "message": f"成交 {trade.stock_code} {trade.traded_volume}股 @ {trade.traded_price:.2f}",
            })

    def on_order_error(self, data):
        if data.order_id in error_orders:
            return
        error_orders.append(data.order_id)
        logger.error(f"{RED}【委托失败】{RESET}错误信息:{data.error_msg.strip()}")
        if self.signal_log is not None:
            self.signal_log.append({
                "type": "error",
                "order_id": str(data.order_id),
                "stock_code": "",
                "order_type": "",
                "price": 0,
                "volume": 0,
                "status": "error",
                "message": f"委托失败: {data.error_msg.strip()}",
            })

    def on_cancel_error(self, data):
        if data.order_id in error_orders:
            return
        error_orders.append(data.order_id)
        logger.error(f"{RED}【撤单失败】{RESET}错误信息:{data.error_msg.strip()}")
        if self.signal_log is not None:
            self.signal_log.append({
                "type": "error",
                "order_id": str(data.order_id),
                "stock_code": "",
                "order_type": "",
                "price": 0,
                "volume": 0,
                "status": "cancel_error",
                "message": f"撤单失败: {data.error_msg.strip()}",
            })


def create_trader(account_id, mini_qmt_path, signal_log=None):
    if sys.platform == 'win32':
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
        except ImportError:
            from backend.mock_xtquant import MockTrader as XtQuantTrader, MockStockAccount as StockAccount
    else:
        from backend.mock_xtquant import MockTrader as XtQuantTrader, MockStockAccount as StockAccount

    session_id = int(random.randint(100000, 999999))
    xt_trader = XtQuantTrader(mini_qmt_path, session_id)
    xt_trader.start()
    connect_result = xt_trader.connect()

    if sys.platform == 'win32':
        if connect_result == 0:
            logger.debug(f"{GREEN}【miniQMT连接成功】{RESET} 路径:{mini_qmt_path}")
    else:
        logger.debug(f"{GREEN}【Mock miniQMT连接成功】{RESET} 路径:{mini_qmt_path}")

    account = StockAccount(account_id)

    if sys.platform == 'win32':
        try:
            from xtquant.xttrader import XtQuantTrader
            xt_trader.subscribe(account)
        except ImportError:
            pass
    logger.debug(f"{GREEN}【账号订阅成功】{RESET} 账号ID:{account_id}")

    callback = MyXtQuantTraderCallback(signal_log=signal_log)

    if sys.platform == 'win32':
        try:
            from xtquant.xttrader import XtQuantTraderCallback
            if isinstance(callback, XtQuantTraderCallback):
                xt_trader.register_callback(callback)
        except ImportError:
            pass
    else:
        callback.on_disconnected = callback.on_disconnected

    return xt_trader, account, callback


def jq_to_qmt(code: str) -> str:
    if code.endswith(".XSHE"):
        return code.replace(".XSHE", ".SZ")
    elif code.endswith(".XSHG"):
        return code.replace(".XSHG", ".SH")
    elif code.endswith(".XBJ"):
        return code.replace(".XBJ", ".BJ")
    return code


def qmt_to_jq(code: str) -> str:
    if code.endswith(".SZ"):
        return code.replace(".SZ", ".XSHE")
    elif code.endswith(".SH"):
        return code.replace(".SH", ".XSHG")
    elif code.endswith(".BJ"):
        return code.replace(".BJ", ".XBJ")
    return code
