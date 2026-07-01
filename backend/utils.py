"""通用工具函数与行情数据获取。

提供时间格式化、订单类型解析、股票后缀补全等通用工具，
以及基于 xtquant 的前收盘价、开盘价、最新价和合约名称获取函数。
"""
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


def normalize_to_qmt(code: str) -> str:
    """将任意平台的股票代码统一归一化为 QMT 格式。

    - 已是 QMT 格式（.SZ/.SH/.BJ） -> 原样返回
    - 聚宽格式（.XSHE/.XSHG/.XBJ） -> 转换为 QMT
    - 其他格式（期货、6 位数字等） -> 原样返回
    """
    if not code:
        return code
    if code.endswith(('.SZ', '.SH', '.BJ')):
        return code
    if code.endswith(('.XSHE', '.XSHG', '.XBJ')):
        return jq_to_qmt(code)
    return code


def fetch_preclose_from_xtdata(stock_codes):
    """从 xtdata 获取前收盘价，返回 {stock_code: preClose} 字典，无真实 xtquant 时 fallback 到 mock"""
    if not stock_codes:
        return {}
    codes = list(stock_codes)
    try:
        from xtquant import xtdata
        xtdata.download_history_data2(codes, '1d')
        result = xtdata.get_market_data(
            field_list=['preClose'],
            stock_list=codes,
            period='1d',
            start_time='',
            end_time='',
            count=1,
            dividend_type='none',
        )
        if not result or 'preClose' not in result:
            return {}
        df = result['preClose']
        preclose_map = {}
        for code in codes:
            if code in df.index:
                vals = df.loc[code].dropna()
                if len(vals) > 0:
                    preclose_map[code] = float(vals.iloc[-1])
        return preclose_map
    except ImportError:
        from backend.mock_xtquant import MockData
        result = MockData.get_market_data(
            field_list=['preClose'],
            stock_list=codes,
            period='1d',
            count=1,
        )
        df = result.get('preClose')
        if df is None:
            return {}
        preclose_map = {}
        for code in codes:
            if code in df.index:
                vals = df.loc[code].dropna()
                if len(vals) > 0:
                    preclose_map[code] = float(vals.iloc[-1])
        return preclose_map
    except Exception:
        return {}


def fetch_stock_names_from_xtdata(stock_codes):
    """从 xtdata 获取股票名称，返回 {stock_code: name} 字典，无真实 xtquant 时 fallback 到 mock"""
    if not stock_codes:
        return {}
    try:
        from xtquant import xtdata
        name_map = {}
        for code in stock_codes:
            try:
                detail = xtdata.get_instrument_detail(code)
                if detail and 'InstrumentName' in detail:
                    name_map[code] = detail['InstrumentName']
            except Exception:
                pass
        return name_map
    except ImportError:
        from backend.mock_xtquant import MockData
        name_map = {}
        for code in stock_codes:
            try:
                detail = MockData.get_instrument_detail(code)
                if detail and 'InstrumentName' in detail:
                    name_map[code] = detail['InstrumentName']
            except Exception:
                pass
        return name_map
    except Exception:
        return {}


def fetch_open_prices_from_xtdata(stock_codes):
    """从 xtdata 获取开盘价，返回 {stock_code: open} 字典，无真实 xtquant 时 fallback 到 mock"""
    if not stock_codes:
        return {}
    codes = list(stock_codes)
    try:
        from xtquant import xtdata
        xtdata.download_history_data2(codes, '1d')
        result = xtdata.get_market_data(
            field_list=['open'],
            stock_list=codes,
            period='1d',
            start_time='',
            end_time='',
            count=1,
            dividend_type='none',
        )
        if not result or 'open' not in result:
            return {}
        df = result['open']
        price_map = {}
        for code in codes:
            if code in df.index:
                vals = df.loc[code].dropna()
                if len(vals) > 0:
                    price_map[code] = float(vals.iloc[-1])
        return price_map
    except ImportError:
        from backend.mock_xtquant import MockData
        result = MockData.get_market_data(
            field_list=['open'],
            stock_list=codes,
            period='1d',
            count=1,
        )
        df = result.get('open')
        if df is None:
            return {}
        price_map = {}
        for code in codes:
            if code in df.index:
                vals = df.loc[code].dropna()
                if len(vals) > 0:
                    price_map[code] = float(vals.iloc[-1])
        return price_map
    except Exception:
        return {}


def fetch_latest_prices_from_xtdata(stock_codes):
    """从 xtdata 获取最新价，返回 {stock_code: last_price} 字典，无真实 xtquant 时 fallback 到 mock。

    使用 get_full_tick 直接获取全推行情中的 lastPrice，无需订阅和等待。
    """
    if not stock_codes:
        return {}
    codes = list(stock_codes)
    try:
        from xtquant import xtdata
        full_tick = xtdata.get_full_tick(codes)
        price_map = {}
        for code in codes:
            tick = full_tick.get(code)
            if tick and tick.get('lastPrice', 0) > 0:
                price_map[code] = float(tick['lastPrice'])
        return price_map
    except ImportError:
        from backend.mock_xtquant import MockData
        full_tick = MockData.get_full_tick(codes)
        price_map = {}
        for code in codes:
            tick = full_tick.get(code)
            if tick and tick.get('lastPrice', 0) > 0:
                price_map[code] = float(tick['lastPrice'])
        return price_map
    except Exception:
        return {}
