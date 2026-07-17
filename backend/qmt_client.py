"""miniQMT 连接层。

创建 XtQuantTrader 实例、注册交易回调、
实现聚宽代码与 QMT 代码的互相转换。
"""
import sys
import random

from backend.order_tracker import OrderTracker
from backend.utils import timestamp_to_datetime_string, parse_order_type, convert_to_current_date
from backend.constants import RED, GREEN, BLUE, RESET, YELLOW
from backend.logger import logger

error_orders = []


class MyXtQuantTraderCallback:
    def __init__(self, order_tracker: OrderTracker = None):
        self.order_tracker = order_tracker

    def on_disconnected(self):
        logger.warning(f"{YELLOW}【连接断开】{RESET}")

    def on_stock_order(self, order):
        if order.order_status == 50:
            logger.info(
                f"{BLUE}【已委托】{RESET} {parse_order_type(order.order_type)} "
                f"代码:{order.stock_code} 名称:{order.order_remark} "
                f"委托价格:{order.price:.2f} 委托数量:{order.order_volume} "
                f"订单编号:{order.order_id} "
                f"委托时间:{timestamp_to_datetime_string(convert_to_current_date(order.order_time))}"
            )

        if self.order_tracker is not None:
            traded_volume = getattr(order, 'traded_volume', 0) or 0
            traded_price = getattr(order, 'traded_price', 0.0) or 0.0
            self.order_tracker.update_from_callback(
                order.order_id, order.order_status, traded_volume, traded_price
            )

    def on_stock_trade(self, trade):
        if self.order_tracker is not None:
            self.order_tracker.update_from_trade(
                trade.order_id, trade.traded_volume, trade.traded_price
            )

    def on_order_error(self, data):
        if data.order_id in error_orders:
            return
        error_orders.append(data.order_id)
        logger.error(f"{RED}【委托失败】{RESET}错误信息:{data.error_msg.strip()}")

        if self.order_tracker is not None:
            self.order_tracker.update_from_error(data.order_id, data.error_msg.strip())

    def on_cancel_error(self, data):
        if data.order_id in error_orders:
            return
        error_orders.append(data.order_id)
        logger.error(f"{RED}【撤单失败】{RESET}错误信息:{data.error_msg.strip()}")


def create_trader(account_id, mini_qmt_path, order_tracker=None, callback=None):
    is_real_xtquant = False

    if sys.platform == 'win32':
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
            is_real_xtquant = True
        except ImportError:
            from backend.mock_xtquant import MockTrader as XtQuantTrader, MockStockAccount as StockAccount
    else:
        from backend.mock_xtquant import MockTrader as XtQuantTrader, MockStockAccount as StockAccount

    session_id = int(random.randint(100000, 999999))
    xt_trader = XtQuantTrader(mini_qmt_path, session_id)
    xt_trader.start()
    connect_result = xt_trader.connect()

    if is_real_xtquant:
        if connect_result == 0:
            logger.debug(f"{GREEN}【miniQMT连接成功】{RESET} 路径:{mini_qmt_path}")
        else:
            raise ConnectionError(
                f"miniQMT连接失败，connect() 返回 {connect_result}，请检查miniQMT是否已启动"
            )
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

    if callback is None:
        callback = MyXtQuantTraderCallback(order_tracker=order_tracker)

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


