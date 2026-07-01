import importlib.util
import os
from pathlib import Path

_TOKEN = "9152b7fa5f07b5c364a21b06c02d1170"

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


def create_client(token: str = None, base_url: str = "http://localhost:8000") -> QMT_LA_Client:
    """创建 QMT 客户端实例

    Args:
        token: 访问令牌，默认从环境变量 QMT_TOKEN 读取
        base_url: API 服务器地址

    Returns:
        QMT_LA_Client 实例
    """
    token = token or _TOKEN
    if not token:
        raise ValueError("必须提供 token 或通过环境变量 QMT_TOKEN 设置")

    return QMT_LA_Client(base_url=base_url, token=token)


def order(
    security: str,
    amount: float,
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格按股数下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        amount: 交易数量，正数买入，负数卖出
        style: 委托类型，None 表示市价单
        side: 'long' 或 'short'，股票暂只支持 'long'
        pindex: subportfolio 序号，默认为 0
        close_today: 是否平今仓，仅部分期货交易所生效
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    return client.api(
        "jukuan_order",
        security=security,
        amount=amount
    )


def order_value(
    security: str,
    value: float,
    side: str = "long",
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格按金额下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        value: 交易金额（元），正数买入，负数卖出
        style: 委托类型，None 表示市价单
        side: 'long' 或 'short'，股票暂只支持 'long'
        pindex: subportfolio 序号，默认为 0
        close_today: 是否平今仓，仅部分期货交易所生效
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    return client.api(
        "jukuan_order_value",
        security=security,
        value=value,
        side=side,
    )


def order_target(
    security: str,
    amount: float,
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格目标股数下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        amount: 期望的最终持仓数量，0 表示清仓
        style: 委托类型，None 表示市价单
        side: 'long' 或 'short'，股票暂只支持 'long'
        pindex: subportfolio 序号，默认为 0
        close_today: 是否平今仓，仅部分期货交易所生效
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    return client.api(
        "jukuan_order_target",
        security=security,
        amount=amount
    )


def order_target_value(
    security: str,
    value: float,
    client: QMT_LA_Client = None,
) -> dict:
    """聚宽风格目标金额下单

    Args:
        security: 标的代码，例如 "000001.XSHE"
        value: 期望的最终持仓市值（元），0 表示清仓
        style: 委托类型，None 表示市价单
        side: 'long' 或 'short'，股票暂只支持 'long'
        pindex: subportfolio 序号，默认为 0
        close_today: 是否平今仓，仅部分期货交易所生效
        client: 可选的 QMT_LA_Client 实例，未传入时自动创建

    Returns:
        服务端返回的下单结果
    """
    client = client or create_client()
    return client.api(
        "jukuan_order_target_value",
        security=security,
        value=value
    )


if __name__ == "__main__":
    client = create_client()

    # 1. 按股数买入 100 股平安银行
    result = order("000001.XSHE", 100, client=client)
    print(f"按股数买入: {result}")

    # # 2. 按金额买入价值 10000 元的平安银行
    # result = order_value("000001.XSHE", 10000, client=client)
    # print(f"按金额买入: {result}")

    # # 3. 按金额卖出价值 5000 元的平安银行
    # result = order_value("000001.XSHE", -5000, client=client)
    # print(f"按金额卖出: {result}")

    # # 4. 将平安银行持仓调整到 200 股
    # result = order_target("000001.XSHE", 8000, client=client)
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
