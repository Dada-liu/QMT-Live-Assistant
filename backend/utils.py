from datetime import datetime
from backend.constants import RED, GREEN, RESET, STOCK_BUY, STOCK_SELL


def add_stock_suffix(stock_code: str) -> str:
    if len(stock_code) != 6 or not stock_code.isdigit():
        raise ValueError("股票代码必须是6位数字")

    if stock_code.startswith(("00", "30", "15", "16", "18", "12")):
        return f"{stock_code}.SZ"
    elif stock_code.startswith(("60", "68", "11")):
        return f"{stock_code}.SH"
    elif stock_code.startswith(("83", "43")):
        return f"{stock_code}.BJ"

    return f"{stock_code}.SH"


def timestamp_to_datetime_string(timestamp: float) -> str:
    dt_object = datetime.fromtimestamp(timestamp)
    return dt_object.strftime('%Y-%m-%d %H:%M:%S')


def parse_order_type(order_type: int) -> str:
    if order_type == STOCK_BUY:
        return f"{RED}买入{RESET}"
    elif order_type == STOCK_SELL:
        return f"{GREEN}卖出{RESET}"
    return f"未知类型({order_type})"


def convert_to_current_date(timestamp: float) -> float:
    dt = datetime.fromtimestamp(timestamp)
    current_date = datetime.now().date()
    new_dt = datetime.combine(current_date, dt.time())
    return new_dt.timestamp()
