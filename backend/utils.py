"""通用工具函数与行情数据获取。

提供时间格式化、订单类型解析、股票后缀补全等通用工具，
以及基于 xtquant 的前收盘价、开盘价、最新价和合约名称获取函数。
"""
from datetime import datetime, time, timedelta
from typing import Optional
from backend.constants import RED, GREEN, RESET, STOCK_BUY, STOCK_SELL
from backend.logger import logger
from backend.qmt_xtconstant import (
    LATEST_PRICE,
    FIX_PRICE,
    MARKET_SH_CONVERT_5_CANCEL,
    MARKET_SH_CONVERT_5_LIMIT,
    MARKET_PEER_PRICE_FIRST,
    MARKET_MINE_PRICE_FIRST,
    MARKET_SZ_INSTBUSI_RESTCANCEL,
    MARKET_SZ_CONVERT_5_CANCEL,
    MARKET_SZ_FULL_OR_CANCEL,
    PRICE_TYPE_SET,
)


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


# ---- 报价类型（price_type）辅助 ----

PRICE_TYPE_NAMES = {
    LATEST_PRICE: "最新价",
    FIX_PRICE: "限价",
    MARKET_SH_CONVERT_5_CANCEL: "最优五档即时成交剩余撤销",
    MARKET_SH_CONVERT_5_LIMIT: "最优五档即时成交剩转限价",
    MARKET_PEER_PRICE_FIRST: "对手方最优",
    MARKET_MINE_PRICE_FIRST: "本方最优",
    MARKET_SZ_INSTBUSI_RESTCANCEL: "即时成交剩余撤销",
    MARKET_SZ_CONVERT_5_CANCEL: "最优五档即时成交剩余撤销(深)",
    MARKET_SZ_FULL_OR_CANCEL: "全额成交或撤销",
}

# 策略可选的市价方式（沪深北三所通用）
MARKET_PRICE_TYPE_SET = frozenset({
    LATEST_PRICE, MARKET_PEER_PRICE_FIRST, MARKET_MINE_PRICE_FIRST,
})

# 各交易所支持的报价类型集合（参考 xtquant 文档：上交所/北交所一组，深交所一组）
_EXCHANGE_PRICE_TYPES = {
    "SH": frozenset({
        LATEST_PRICE, FIX_PRICE, MARKET_SH_CONVERT_5_CANCEL,
        MARKET_SH_CONVERT_5_LIMIT, MARKET_PEER_PRICE_FIRST, MARKET_MINE_PRICE_FIRST,
    }),
    "BJ": frozenset({
        LATEST_PRICE, FIX_PRICE, MARKET_SH_CONVERT_5_CANCEL,
        MARKET_SH_CONVERT_5_LIMIT, MARKET_PEER_PRICE_FIRST, MARKET_MINE_PRICE_FIRST,
    }),
    "SZ": frozenset({
        LATEST_PRICE, FIX_PRICE, MARKET_PEER_PRICE_FIRST, MARKET_MINE_PRICE_FIRST,
        MARKET_SZ_INSTBUSI_RESTCANCEL, MARKET_SZ_CONVERT_5_CANCEL, MARKET_SZ_FULL_OR_CANCEL,
    }),
}

_EXCHANGE_NAMES = {"SH": "上交所", "SZ": "深交所", "BJ": "北交所"}


def _market_from_suffix(stock_code: str) -> Optional[str]:
    """按 QMT 后缀判断交易所，无法识别（期货等）返回 None。"""
    code = (stock_code or "").strip().upper()
    for suffix, market in ((".SH", "SH"), (".SZ", "SZ"), (".BJ", "BJ")):
        if code.endswith(suffix):
            return market
    return None


def is_market_price_type(price_type: Optional[int]) -> bool:
    """限价(11)以外的报价类型均为市价类，下单时委托价置 0。"""
    return price_type is not None and price_type != FIX_PRICE


def price_type_name(price_type: Optional[int]) -> str:
    """返回报价类型中文名，用于日志与展示。"""
    if price_type is None:
        return "未知"
    return PRICE_TYPE_NAMES.get(price_type, f"未知类型({price_type})")


def validate_price_type_for_market(stock_code: str, price_type: Optional[int]) -> None:
    """集中校验报价类型合法性及与证券所属交易所的兼容性。

    - None：放行（调用方自行推导默认值）；
    - 不在 PRICE_TYPE_SET：ValueError；
    - 市场可识别但不兼容（如深交所股票用上交所专属类型）：ValueError；
    - 市场无法识别（期货等）：仅做集合校验，跳过兼容性检查。
    """
    if price_type is None:
        return
    if price_type not in PRICE_TYPE_SET:
        raise ValueError(f"不支持的 price_type: {price_type}")
    market = _market_from_suffix(stock_code)
    if market is None:
        return
    if price_type not in _EXCHANGE_PRICE_TYPES[market]:
        raise ValueError(
            f"报价类型 {price_type}（{price_type_name(price_type)}）"
            f"不支持{_EXCHANGE_NAMES[market]}证券: {stock_code}"
        )


def seconds_until_market_open(target_hour: int = 9, target_minute: int = 30) -> float:
    """计算到下一个市场开盘时刻的秒数。

    默认目标为当天 09:30；若当前时间已过，则计算到次日 09:30。
    返回秒数，可为小数（含微秒精度）。
    """
    now = datetime.now()
    target = datetime.combine(now.date(), time(target_hour, target_minute))
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


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
    except Exception as e:
        logger.error(f"【行情获取失败】fetch_preclose_from_xtdata 异常: {e} | codes={codes}", exc_info=True)
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
    except Exception as e:
        logger.error(f"【行情获取失败】fetch_stock_names_from_xtdata 异常: {e} | codes={stock_codes}", exc_info=True)
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
    except Exception as e:
        logger.error(f"【行情获取失败】fetch_open_prices_from_xtdata 异常: {e} | codes={codes}", exc_info=True)
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
    except Exception as e:
        logger.error(f"【行情获取失败】fetch_latest_prices_from_xtdata 异常: {e} | codes={codes}", exc_info=True)
        return {}


class QMTInteractionError(Exception):
    """QMT 同步接口返回失败或抛异常时的统一错误。"""


def _is_qmt_failure(method_name: str, result) -> tuple:
    """根据 xtquant 文档判断返回值是否代表失败，并返回 (is_failure, reason)。"""
    if method_name in (
        "order_stock", "order_stock_async",
        "smt_negotiate_order_async",
    ):
        return result == -1, f"{method_name} 返回 -1，委托失败"
    if method_name in (
        "cancel_order_stock", "cancel_order_stock_async",
        "cancel_order_stock_sysid", "cancel_order_stock_sysid_async",
    ):
        return result == -1, f"{method_name} 返回 -1，撤单失败"
    if method_name.startswith("query_"):
        return result is None, f"{method_name} 返回 None，查询失败"
    return False, ""


def qmt_call(trader, method_name: str, *args, context: dict = None, **kwargs):
    """统一调用 QMT 同步接口。

    1. 捕获异常并记录结构化日志；
    2. 按 xtquant 文档检查返回值；
    3. 失败时抛出 QMTInteractionError，原值作为 cause。

    Args:
        trader: XtQuantTrader / MockTrader 实例。
        method_name: 要调用的方法名。
        context: 用于日志的额外上下文，如 {"stock_code": "...", "order_id": ...}。
    """
    method = getattr(trader, method_name)
    try:
        result = method(*args, **kwargs)
    except Exception as exc:
        ctx = context or {}
        logger.error(
            f"【QMT 调用异常】{method_name} 调用失败: {exc} | 上下文: {ctx}",
            exc_info=True,
        )
        raise QMTInteractionError(
            f"{method_name} 调用失败: {exc}"
        ) from exc

    failed, reason = _is_qmt_failure(method_name, result)
    if failed:
        ctx = context or {}
        logger.error(f"【QMT 调用失败】{reason} | 上下文: {ctx}")
        raise QMTInteractionError(reason)

    return result


def build_server_url(host: str, port: int, root_path: str = "") -> str:
    """构建本地访问 URL。

    - 当 host 为 0.0.0.0 或 :: 时，回退到 127.0.0.1，便于本地浏览器/桌面壳访问。
    - 当传入 root_path 时，拼接到 base URL 之后，支持 nginx 子路径代理。
    """
    effective_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    base = f"http://{effective_host}:{port}"
    if root_path:
        base = f"{base}/{root_path.lstrip('/')}"
    return base
