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
        self.order_volume = 100
        self.order_remark = "平安银行"
        self.order_status = 56
        self.order_time = 1750000000.0


class MockAsset:
    def __init__(self):
        self.account_id = "test_account"
        self.cash = 100000.00
        self.market_value = 50000.00
        self.total_asset = 150000.00
        self.frozen_cash = 0.00
        self.fetch_balance = 100000.00


class MockTrader:
    def __init__(self, mini_qmt_path, session_id):
        self.mini_qmt_path = mini_qmt_path
        self.session_id = session_id
        self._callbacks = []

    def start(self):
        return True

    def connect(self):
        return True

    def subscribe(self, account):
        pass

    def register_callback(self, callback):
        self._callbacks.append(callback)

    def query_stock_asset(self, account):
        return MockAsset()

    def order_stock(self, account, stock_code, order_type, order_volume, price, strategy_name="", remark=""):
        return 100001

    def cancel_order(self, account, order_id):
        return True

    def query_stock_orders(self, account):
        return [MockOrder()]

    def query_stock_trades(self, account):
        return [MockTrade()]

    def query_stock_positions(self, account):
        return []

    def query_all_orders(self, account):
        return [MockOrder()]

    def query_all_trades(self, account):
        return [MockTrade()]


class MockData:
    @staticmethod
    def set_qmt_data_dir(path):
        pass
