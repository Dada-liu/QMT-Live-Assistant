import importlib.util
import os
from pathlib import Path

_TOKEN = os.getenv("QMT_TOKEN", "")

def _load_client_class():
    """动态加载带横杠文件名的客户端模块"""
    client_path = Path(__file__).parent / "qmt-live-asistant-client.py"
    spec = importlib.util.spec_from_file_location(
        "qmt_live_asistant_client", client_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.QMT_LA_Client


QMT_LA_Client = _load_client_class()


def create_client(token: str = None, base_url: str = None) -> QMT_LA_Client:
    """创建 QMT 客户端实例

    Args:
        token: 访问令牌，默认从环境变量 QMT_TOKEN 读取
        base_url: API 服务器地址，默认从环境变量 QMT_BASE_URL 读取，未设置时使用 http://localhost:8000

    Returns:
        QMT_LA_Client 实例
    """
    token = token or _TOKEN
    base_url = base_url or os.getenv("QMT_BASE_URL", "http://localhost:8000")
    if not token:
        raise ValueError("必须提供 token 或通过环境变量 QMT_TOKEN 设置")

    return QMT_LA_Client(base_url=base_url, token=token)


def order(
    security: str,
    amount: float,
    notify_source: bool = False,
    source_platform_webhook: str = "",
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格按股数下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        amount: 交易数量，正数买入，负数卖出
        notify_source: 是否在订单状态变更时通知源平台
        source_platform_webhook: 源平台回调地址
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    params = {
        "security": security,
        "amount": amount,
    }
    if notify_source:
        params["notify_source"] = notify_source
    if source_platform_webhook:
        params["source_platform_webhook"] = source_platform_webhook
    return client.api("jukuan_order", **params)


def order_value(
    security: str,
    value: float,
    side: str = "long",
    notify_source: bool = False,
    source_platform_webhook: str = "",
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格按金额下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        value: 交易金额（元），正数买入，负数卖出
        side: 'long' 或 'short'，股票暂只支持 'long'
        notify_source: 是否在订单状态变更时通知源平台
        source_platform_webhook: 源平台回调地址
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    params = {
        "security": security,
        "value": value,
        "side": side,
    }
    if notify_source:
        params["notify_source"] = notify_source
    if source_platform_webhook:
        params["source_platform_webhook"] = source_platform_webhook
    return client.api("jukuan_order_value", **params)


def order_target(
    security: str,
    amount: float,
    notify_source: bool = False,
    source_platform_webhook: str = "",
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格目标股数下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        amount: 期望的最终持仓数量，0 表示清仓
        notify_source: 是否在订单状态变更时通知源平台
        source_platform_webhook: 源平台回调地址
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    params = {
        "security": security,
        "amount": amount,
    }
    if notify_source:
        params["notify_source"] = notify_source
    if source_platform_webhook:
        params["source_platform_webhook"] = source_platform_webhook
    return client.api("jukuan_order_target", **params)


def order_target_value(
    security: str,
    value: float,
    notify_source: bool = False,
    source_platform_webhook: str = "",
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格目标金额下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        value: 期望的最终持仓市值（元），0 表示清仓
        notify_source: 是否在订单状态变更时通知源平台
        source_platform_webhook: 源平台回调地址
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    params = {
        "security": security,
        "value": value,
    }
    if notify_source:
        params["notify_source"] = notify_source
    if source_platform_webhook:
        params["source_platform_webhook"] = source_platform_webhook
    return client.api("jukuan_order_target_value", **params)


def generic_order(
    security: str,
    direction: str,
    quantity: int,
    price: float = 0.0,
    price_type: int = None,
    order_type: int = None,
    strategy_name: str = "generic_order",
    order_remark: str = "",
    source_platform: str = "",
    notify_source: bool = False,
    source_platform_webhook: str = "",
    client: QMT_LA_Client = None,
) -> dict:
    """通用下单接口

    Args:
        security: 标的代码，例如 "000001.XSHE"
        direction: 下单方向，"buy" 或 "sell"
        quantity: 委托数量
        price: 委托价格，0 表示市价
        price_type: 报价类型，如 5=最新价，11=限价
        order_type: xtquant 委托类型，如 23=买入，24=卖出
        strategy_name: 策略名称
        order_remark: 订单备注
        source_platform: 信号来源平台
        notify_source: 是否在订单状态变更时通知源平台
        source_platform_webhook: 源平台回调地址
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    params = {
        "security": security,
        "direction": direction,
        "quantity": quantity,
        "price": price,
        "strategy_name": strategy_name,
        "order_remark": order_remark,
    }
    if price_type is not None:
        params["price_type"] = price_type
    if order_type is not None:
        params["order_type"] = order_type
    if source_platform:
        params["source_platform"] = source_platform
    if notify_source:
        params["notify_source"] = notify_source
    if source_platform_webhook:
        params["source_platform_webhook"] = source_platform_webhook
    return client.api("order", **params)


if __name__ == "__main__":
    client = create_client()

    # # 1. 按股数买入 100 股平安银行
    result = order("000001.XSHE", 1000, client=client)
    print(f"按股数买入: {result}")

    # # 2. 按金额买入价值 10000 元的平安银行
    # result = order_value("000001.XSHE", -10000, client=client)
    # print(f"按金额买入: {result}")

    # # 3. 按金额卖出价值 5000 元的平安银行
    # result = order_value("000001.XSHE", -5000, client=client)
    # print(f"按金额卖出: {result}")

    # # 4. 将平安银行持仓调整到 200 股
    # result = order_target("000001.XSHE", 800, client=client)
    # print(f"目标股数调仓: {result}")

    # # 5. 将平安银行持仓全部清仓
    # result = order_target("000001.XSHE", 0, client=client)
    # print(f"目标股数清仓: {result}")

    # # 6. 将平安银行持仓市值调整到 50000 元
    # result = order_target_value("000001.XSHE", 50000, client=client)
    # print(f"目标市值调仓: {result}")

    # # 7. 将平安银行持仓市值调整到 0，全部清仓
    # result = order_target_value("000001.XSHE", 0, client=client)
    # print(f"目标市值清仓: {result}")
