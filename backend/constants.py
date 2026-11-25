"""常量定义模块。

定义 ANSI 颜色码、订单状态映射、基础订单类型等运行时常量。
"""
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

ORDER_STATUS_MAP = {
    48: "未报",
    49: "待报",
    50: "已报",
    51: "已报待撤",
    52: "部成待撤",
    53: "部撤",
    54: "已撤",
    55: "部成",
    56: "已成",
    57: "废单",
}

STOCK_BUY = 23
STOCK_SELL = 24

# 策略可用资金不足时的处理策略
INSUFFICIENT_FUNDS_REJECT = 'reject'
INSUFFICIENT_FUNDS_MAX_BUYABLE = 'max_buyable'
INSUFFICIENT_FUNDS_POLICIES = (INSUFFICIENT_FUNDS_REJECT, INSUFFICIENT_FUNDS_MAX_BUYABLE)

# 策略种类（券种）
SECURITY_TYPE_STOCK = 'stock'
SECURITY_TYPE_CONVERTIBLE_BOND = 'convertible_bond'
SECURITY_TYPES = (SECURITY_TYPE_STOCK, SECURITY_TYPE_CONVERTIBLE_BOND)
SECURITY_TYPE_NAMES = {
    SECURITY_TYPE_STOCK: "股票",
    SECURITY_TYPE_CONVERTIBLE_BOND: "可转债",
}

ORDER_TYPE_MAP = {
    23: "买入",
    24: "卖出",
    27: "融资买入",
    28: "融券卖出",
    29: "买券还券",
    30: "卖券还款",
}
