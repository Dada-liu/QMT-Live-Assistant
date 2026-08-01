"""非 Windows 平台的 xtquant Mock 实现。

提供 MockTrader、MockData 等类，用于在 macOS/Linux 环境下进行开发测试，
模拟 xtquant 的交易接口与行情数据接口。
"""
import time

class MockTraderCallback:
    def on_disconnected(self): pass
    def on_stock_order(self, order): pass
    def on_stock_trade(self, trade): pass
    def on_order_error(self, data): pass
    def on_cancel_error(self, data): pass
    def on_order_stock_async_response(self, response): pass


class MockStockAccount:
    def __init__(self, account_id):
        self.account_id = account_id


class MockTrade:
    def __init__(self):
        self.order_id = "mock-trade-" + str(id(self))
        self.stock_code = "000001.SZ"
        self.order_type = 23
        self.traded_price = 12.50
        self.traded_volume = 100
        self.order_remark = "平安银行"
        self.traded_time = 1750000000.0


class MockOrder:
    def __init__(self):
        self.order_id = 100001
        self.stock_code = "000001.SZ"
        self.order_type = 23
        self.price = 12.50
        self.price_type = 11
        self.order_volume = 100
        self.order_remark = "平安银行"
        self.order_status = 56
        self.order_time = 1750000000.0
        self.traded_volume = 0
        self.traded_price = 0.0


class MockPosition:
    def __init__(self, stock_code="000001.SZ", volume=100, market_value=1250.0,
                 open_price=12.0, can_use_volume=100):
        self.account_type = 2
        self.account_id = "test_account"
        self.stock_code = stock_code
        self.volume = volume
        self.can_use_volume = can_use_volume
        self.open_price = open_price
        self.market_value = market_value
        self.frozen_volume = 0
        self.on_road_volume = 0
        self.yesterday_volume = 0
        self.direction = 0


class MockAsset:
    def __init__(self):
        self.account_id = "test_account"
        self.cash = 100000.00
        self.market_value = 451250.00
        self.total_asset = 551250.00
        self.frozen_cash = 0.00
        self.fetch_balance = 100000.00


class MockTrader:
    _order_counter = 100000

    def __init__(self, mini_qmt_path, session_id):
        self.mini_qmt_path = mini_qmt_path
        self.session_id = session_id
        self._callbacks = []
        self._orders = {}
        self._disconnected = False

    def start(self):
        return True

    def connect(self):
        return True

    def stop(self):
        return True

    def subscribe(self, account):
        pass

    def register_callback(self, callback):
        self._callbacks.append(callback)

    def simulate_disconnect(self):
        self._disconnected = True
        for callback in self._callbacks:
            try:
                callback.on_disconnected()
            except Exception:
                pass

    def simulate_reconnect(self):
        self._disconnected = False

    def _check_connection(self):
        if self._disconnected:
            raise ConnectionError("Mock QMT connection is disconnected")

    def query_stock_asset(self, account):
        self._check_connection()
        return MockAsset()

    def order_stock(self, account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""):
        self._check_connection()
        MockTrader._order_counter += 1
        order_id = MockTrader._order_counter

        order = MockOrder()
        order.order_id = order_id
        order.stock_code = stock_code
        order.order_type = order_type
        order.price = price if price > 0 else 12.50
        order.price_type = price_type
        order.order_volume = order_volume
        order.order_remark = order_remark or ""
        order.order_status = 50
        order.order_time = 1750000000.0
        order.traded_volume = 0
        order.traded_price = 0.0

        self._orders[str(order_id)] = order
        return order_id

    def bump_order_counter(self, min_counter: int) -> None:
        """将订单号计数器抬升到不小于 min_counter。

        计数器是类属性，每次进程启动都从 100000 重新计数；服务器重启后若数据库中
        已存在历史 mock 订单号，新订单号会与之冲突并覆盖内存/数据库中的旧订单。
        启动时由 QMTServer 调用本方法避免冲突。
        """
        if min_counter > MockTrader._order_counter:
            MockTrader._order_counter = min_counter

    def cancel_order_stock(self, account, order_id):
        """根据订单编号撤单；成功返回 0，失败返回 -1。"""
        order = self._orders.get(str(order_id))
        if order is None:
            return -1
        order.order_status = 54
        return 0

    def cancel_order(self, account, order_id):
        """旧接口别名，内部转发到 cancel_order_stock。"""
        return self.cancel_order_stock(account, order_id)

    def _advance_order_if_needed(self, order):
        """模拟订单状态推进：已报 -> 已成，并触发回调。"""
        if order.order_status == 50:
            order.order_status = 56
            order.traded_volume = order.order_volume
            order.traded_price = order.price

            for callback in self._callbacks:
                try:
                    callback.on_stock_order(order)
                    trade = MockTrade()
                    trade.order_id = order.order_id
                    trade.stock_code = order.stock_code
                    trade.order_type = order.order_type
                    trade.traded_price = order.price
                    trade.traded_volume = order.order_volume
                    trade.order_remark = order.order_remark
                    callback.on_stock_trade(trade)
                except Exception:
                    pass

    def query_stock_order(self, account, order_id):
        self._check_connection()
        order = self._orders.get(str(order_id))
        if not order:
            return None

        self._advance_order_if_needed(order)
        return order

    def query_stock_orders(self, account, cancelable_only=False):
        self._check_connection()
        for order in self._orders.values():
            self._advance_order_if_needed(order)
        return list(self._orders.values())

    def query_stock_trades(self, account):
        self._check_connection()
        return [MockTrade()]

    def query_stock_positions(self, account):
        self._check_connection()
        # 当前市值 = K线 close × volume，与 preClose 有差异以产生有意义当日盈亏
        return [
            MockPosition("000001.SZ", volume=500, market_value=6275.0, open_price=12.0, can_use_volume=500),
            MockPosition("600519.SH", volume=200, market_value=361000.0, open_price=1750.0, can_use_volume=200),
            MockPosition("300750.SZ", volume=1000, market_value=85100.0, open_price=82.0, can_use_volume=800),
        ]

    def query_all_orders(self, account):
        return list(self._orders.values())

    def query_all_trades(self, account):
        return [MockTrade()]


class MockData:
    # 模拟行情数据，key=股票代码，value=最新K线字典
    _MOCK_KLINE = {
        "000001.SZ": {"open": 12.45, "high": 12.58, "low": 12.40, "close": 12.55, "preClose": 12.50},
        "600519.SH": {"open": 1795.0, "high": 1810.0, "low": 1790.0, "close": 1805.0, "preClose": 1800.0},
        "300750.SZ": {"open": 84.50, "high": 85.20, "low": 84.00, "close": 85.10, "preClose": 85.00},
        "002830.SZ": {"open": 11.80, "high": 12.10, "low": 11.75, "close": 12.00, "preClose": 11.90},
        "002888.SZ": {"open": 17.50, "high": 18.20, "low": 17.40, "close": 18.00, "preClose": 17.60},
        "002188.SZ": {"open": 6.30, "high": 6.60, "low": 6.25, "close": 6.50, "preClose": 6.35},
        "003003.SZ": {"open": 8.80, "high": 9.10, "low": 8.75, "close": 9.00, "preClose": 8.85},
        "002200.SZ": {"open": 4.30, "high": 4.55, "low": 4.25, "close": 4.50, "preClose": 4.35},
    }
    _MOCK_TIME = "20260609"

    @staticmethod
    def set_qmt_data_dir(path):
        pass

    @staticmethod
    def download_history_data2(stock_list, period, start_time='', end_time='', callback=None):
        pass

    @staticmethod
    def subscribe_quote(stock_code, period, start_time='', end_time='', count=-1, callback=None):
        """模拟订阅实时行情，无实际操作"""
        pass

    @staticmethod
    def get_full_tick(stock_list):
        """模拟全推行情，返回 {stock_code: {'lastPrice': price, ...}} 字典"""
        if not stock_list:
            return {}
        result = {}
        for code in stock_list:
            if code in MockData._MOCK_KLINE:
                kline = MockData._MOCK_KLINE[code]
                result[code] = {
                    "lastPrice": kline["close"],
                    "open": kline["open"],
                    "high": kline["high"],
                    "low": kline["low"],
                    "lastClose": kline["preClose"],
                }
        return result

    @staticmethod
    def get_market_data(field_list=None, stock_list=None, period=None,
                        start_time=None, end_time=None, count=None,
                        dividend_type=None, fill_data=None):
        """返回 {field: DataFrame(index=股票代码, columns=时间)}"""
        import pandas as pd
        if not stock_list:
            stock_list = list(MockData._MOCK_KLINE.keys())
        if not field_list:
            field_list = ["open", "high", "low", "close", "preClose"]
        result = {}
        for field in field_list:
            data = {}
            for code in stock_list:
                if code in MockData._MOCK_KLINE:
                    data[code] = MockData._MOCK_KLINE[code].get(field, float("nan"))
            if data:
                result[field] = pd.DataFrame({MockData._MOCK_TIME: data})
        return result

    @staticmethod
    def get_market_data_ex(field_list=None, stock_list=None, period=None,
                           start_time=None, end_time=None, count=None,
                           dividend_type=None, fill_data=None):
        """返回 {股票代码: DataFrame(index=时间, columns=字段)}"""
        import pandas as pd
        if not stock_list:
            stock_list = list(MockData._MOCK_KLINE.keys())
        if not field_list:
            field_list = ["open", "high", "low", "close", "preClose"]
        result = {}
        for code in stock_list:
            if code in MockData._MOCK_KLINE:
                row = {}
                for field in field_list:
                    row[field] = MockData._MOCK_KLINE[code].get(field, float("nan"))
                result[code] = pd.DataFrame([row], index=[MockData._MOCK_TIME])
        return result

    @staticmethod
    def get_instrument_detail(stock_code):
        names = {
            "000001.SZ": "平安银行",
            "600519.SH": "贵州茅台",
            "300750.SZ": "宁德时代",
            "002830.SZ": "名雕股份",
            "002888.SZ": "惠威科技",
            "002188.SZ": "中天服务",
            "003003.SZ": "天元股份",
            "002200.SZ": "交投控股",
        }
        return {
            "InstrumentName": names.get(stock_code, ""),
            "ExchangeID": stock_code.split(".")[-1] if "." in stock_code else "",
            "InstrumentID": stock_code.split(".")[0] if "." in stock_code else stock_code,
        }
