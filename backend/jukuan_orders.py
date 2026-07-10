"""聚宽风格下单处理器。

提供聚宽 API 风格的下单方法（order/order_target/order_value/order_target_value），
支持证券代码自动转换、按手数取整、期货空头处理，以及无持仓时行情取价。
"""
from typing import Optional
from backend.utils import fetch_latest_prices_from_xtdata, qmt_to_jq
from backend.qmt_client import create_trader
from backend.logger import logger
from backend.constants import GREEN, BLUE, YELLOW, RESET, STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import LATEST_PRICE, FIX_PRICE

FUTURE_EXCHANGES = {'.CCFX', '.XDCE', '.XSGE', '.XZCE'}


def _is_future(code: str) -> bool:
    """判断证券代码是否为期货品种。"""
    for suffix in FUTURE_EXCHANGES:
        if code.endswith(suffix):
            return True
    return False


def _lot_size(code: str) -> int:
    """获取证券每手数量，期货为1手，股票为100手。"""
    return 1 if _is_future(code) else 100


def _round_down_to_lot(quantity: float, code: str) -> int:
    """将下单数量向下取整到最近手数倍，避免非整手委托。"""
    size = _lot_size(code)
    return int(quantity / size) * size


def _get_position_info(trader, account, stock_code: str) -> dict:
    """查询指定 QMT 代码在账户中的持仓信息。

    返回包含持仓数量、参考价格以及是否找到持仓的字典。
    """
    try:
        positions = trader.query_stock_positions(account)
    except Exception:
        positions = []

    for pos in positions:
        pos_code = getattr(pos, 'stock_code', '')
        if pos_code != stock_code:
            continue
        volume = getattr(pos, 'volume', 0) or 0
        market_value = getattr(pos, 'market_value', 0.0) or 0.0
        if volume > 0 and market_value > 0:
            price = market_value / volume
        else:
            price = getattr(pos, 'open_price', 0.0) or 0.0
        return {
            'volume': volume,
            'price': price,
            'found': True,
        }

    return {'volume': 0, 'price': 0.0, 'found': False}


def _get_price(
    trader, account, stock_code: str,
    strategy_manager=None, strategy_id: Optional[str] = None
) -> float:
    """获取指定 QMT 代码的最新参考价格。

    若提供 strategy_id，优先读取策略持仓 avg_cost；否则优先使用账户持仓市值，
    无持仓时从行情接口获取。
    """
    if strategy_id and strategy_manager is not None:
        strategy = strategy_manager.get(strategy_id)
        if strategy:
            pos = next(
                (p for p in strategy.positions if p["stock_code"] == stock_code), None
            )
            if pos and pos.get("avg_cost", 0.0) > 0:
                return pos["avg_cost"]

    info = _get_position_info(trader, account, stock_code)
    if info['price'] > 0:
        return info['price']

    # 无持仓时，从 QMT 行情接口获取最新价
    price_map = fetch_latest_prices_from_xtdata([stock_code])
    price = price_map.get(stock_code, 0.0)
    if price > 0:
        return price

    raise ValueError(f"无法获取 {stock_code} 的最新价格，请确保持仓中有该股票或行情接口可用")


def _get_volume(
    trader, account, stock_code: str,
    strategy_manager=None, strategy_id: Optional[str] = None
) -> int:
    """获取指定 QMT 代码的当前持仓数量。

    若提供 strategy_id，返回策略持仓数量；否则返回账户持仓数量。
    """
    if strategy_id and strategy_manager is not None:
        strategy = strategy_manager.get(strategy_id)
        if strategy:
            pos = next(
                (p for p in strategy.positions if p["stock_code"] == stock_code), None
            )
            return pos["quantity"] if pos else 0

    info = _get_position_info(trader, account, stock_code)
    return info['volume']


class JukuanOrderHandler:
    """处理聚宽策略信号并转换为QMT实际委托的下单处理器。"""

    def __init__(self, trader, account, strategy_manager=None):
        """初始化下单处理器。

        Args:
            trader: QMT交易对象，用于调用下单与持仓查询接口。
            account: 资金账号。
            strategy_manager: 可选，策略管理器。
        """
        self.trader = trader
        self.account = account
        self.strategy_manager = strategy_manager

    def _get_strategy_position(self, strategy_id: str, stock_code: str) -> Optional[dict]:
        """获取策略下某只股票的持仓字典。"""
        if not strategy_id or self.strategy_manager is None:
            return None
        strategy = self.strategy_manager.get(strategy_id)
        if not strategy:
            return None
        return next(
            (p for p in strategy.positions if p["stock_code"] == stock_code), None
        )

    def _get_strategy_quantity(self, strategy_id: str, stock_code: str) -> int:
        """获取策略下某只股票的总持仓数量。"""
        pos = self._get_strategy_position(strategy_id, stock_code)
        return pos["quantity"] if pos else 0

    def _get_strategy_available_quantity(self, strategy_id: str, stock_code: str) -> int:
        """获取策略下某只股票的可用持仓数量。"""
        pos = self._get_strategy_position(strategy_id, stock_code)
        return pos.get("available_quantity", 0) if pos else 0

    def _get_strategy_available_cash(self, strategy_id: str) -> float:
        """获取策略可用资金。"""
        if not strategy_id or self.strategy_manager is None:
            return 0.0
        strategy = self.strategy_manager.get(strategy_id)
        return strategy.available_cash if strategy else 0.0

    def _check_strategy_sell_available(
        self, stock_code: str, quantity: int, strategy_id: Optional[str]
    ) -> None:
        """当按策略 token 卖出时，检查策略持仓可用数量是否足够。"""
        if not strategy_id or self.strategy_manager is None:
            return
        available = self._get_strategy_available_quantity(strategy_id, stock_code)
        if available < quantity:
            raise ValueError(
                f"策略可用持仓不足: {stock_code} 可用 {available} 股, 需要卖出 {quantity} 股"
            )

    def _check_strategy_buy_cash(
        self, stock_code: str, quantity: int, price: float, strategy_id: Optional[str]
    ) -> None:
        """当按策略 token 买入且能确定成本时，检查策略可用资金是否足够。"""
        if not strategy_id or self.strategy_manager is None or price <= 0:
            return
        available_cash = self._get_strategy_available_cash(strategy_id)
        cost = quantity * price
        if available_cash < cost:
            raise ValueError(
                f"策略可用资金不足: {stock_code} 需要 {cost:.2f}, 可用 {available_cash:.2f}"
            )

    def _submit_order(self, stock_code: str, order_type: int, quantity: int,
                      price: float = 0.0,
                      strategy_name: str = 'jukuan_order',
                      strategy_id: Optional[str] = None) -> int:
        """向QMT提交一笔委托。

        Args:
            stock_code: QMT格式的证券代码。
            order_type: 委托类型（买入或卖出）。
            quantity: 委托数量，已按手数取整。
            price: 参考价格，用于策略级资金校验。
            strategy_name: 策略名称，写入QMT订单备注。
            strategy_id: 策略ID，用于校验策略持仓可用数量与资金。

        Returns:
            QMT返回的订单编号。
        """
        if order_type == STOCK_SELL:
            self._check_strategy_sell_available(stock_code, quantity, strategy_id)
        elif order_type == STOCK_BUY:
            self._check_strategy_buy_cash(stock_code, quantity, price, strategy_id)

        if price > 0:
            price_type = FIX_PRICE
            order_price = price
        else:
            price_type = LATEST_PRICE
            order_price = 0

        jq_code = qmt_to_jq(stock_code)
        order_id = self.trader.order_stock(
            self.account,
            stock_code=stock_code,
            order_type=order_type,
            order_volume=quantity,
            price_type=price_type,
            price=order_price,
            strategy_name=strategy_name,
            order_remark=jq_code,
        )
        logger.info(
            f"{BLUE}【聚宽下单】{RESET} "
            f"股票:{jq_code}→{stock_code} "
            f"类型:{'买入' if order_type == STOCK_BUY else '卖出'} "
            f"数量:{quantity} "
            f"价格类型:{'限价' if price > 0 else '市价'} "
            f"价格:{order_price:.2f} "
            f"订单编号:{order_id}"
        )
        return order_id

    # ---- (1) jukuan_order ----

    def jukuan_order(self, stock_code: str, amount: int,
                     side: str = 'long', strategy_id: Optional[str] = None) -> dict:
        """按指定数量下单。

        根据 amount 的正负决定买入或卖出，已支持期货空头方向处理。
        数量会按每手股数向下取整，不足一手的委托将被取消。

        Args:
            stock_code: QMT格式的证券代码。
            amount: 目标数量，正数为买入/开多，负数为卖出/平多。
            side: 方向，'long' 或 'short'，仅对期货生效。
            strategy_id: 策略ID，卖出时校验策略持仓可用数量。

        Returns:
            包含 order_id、direction、quantity、message 的字典。
        """
        is_future = _is_future(stock_code)
        quantity = _round_down_to_lot(abs(amount), stock_code)

        if quantity == 0:
            msg = f"下单数量不足一手，调整为0股，订单取消"
            logger.warning(f"{YELLOW}【聚宽下单】{RESET} {stock_code} {msg}")
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': 0.0,
                'order_type': None,
                'message': msg,
            }

        if is_future and side == 'short':
            order_type = STOCK_SELL if amount > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if amount > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        price = _get_price(
            self.trader, self.account, stock_code,
            strategy_manager=self.strategy_manager, strategy_id=strategy_id,
        )

        try:
            order_id = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            msg = f"聚宽下单: {direction} {stock_code} {quantity}股"
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': quantity,
                'price': price,
                'order_type': order_type,
                'message': msg,
            }
        except Exception as e:
            msg = f"下单失败: {str(e)}"
            raise

    # ---- (2) jukuan_order_target ----

    def jukuan_order_target(self, stock_code: str, amount: int,
                            side: str = 'long', strategy_id: Optional[str] = None) -> dict:
        """按目标持仓数量调仓。

        计算当前持仓与目标数量的差值，并委托买入或卖出差额部分。

        Args:
            stock_code: QMT格式的证券代码。
            amount: 目标持仓数量。
            side: 方向，'long' 或 'short'，仅对期货生效。
            strategy_id: 策略ID，卖出时校验策略持仓可用数量。

        Returns:
            包含 order_id、direction、quantity、message 的字典。
        """
        if strategy_id and self.strategy_manager is not None:
            current_qty = self._get_strategy_quantity(strategy_id, stock_code)
        else:
            current_qty = _get_volume(self.trader, self.account, stock_code)
        delta = amount - current_qty

        if delta == 0:
            msg = f"目标数量已满足 (当前:{current_qty}, 目标:{amount})，不再调整"
            logger.info(f"{GREEN}【聚宽调仓】{RESET} {stock_code} {msg}")
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': 0.0,
                'order_type': None,
                'message': msg,
            }

        is_future = _is_future(stock_code)
        quantity = _round_down_to_lot(abs(delta), stock_code)

        if quantity == 0:
            msg = f"调整数量不足一手 (delta:{delta})，订单取消"
            logger.warning(f"{YELLOW}【聚宽调仓】{RESET} {stock_code} {msg}")
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': 0.0,
                'order_type': None,
                'message': msg,
            }

        if is_future and side == 'short':
            order_type = STOCK_SELL if delta > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if delta > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        price = _get_price(
            self.trader, self.account, stock_code,
            strategy_manager=self.strategy_manager, strategy_id=strategy_id,
        )

        try:
            order_id = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            msg = f"聚宽调仓: {direction} {stock_code} {quantity}股 (当前:{current_qty}→目标:{amount})"
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': quantity,
                'price': price,
                'order_type': order_type,
                'message': msg,
            }
        except Exception as e:
            msg = f"调仓失败: {str(e)}"
            raise

    # ---- (3) jukuan_order_value ----

    def jukuan_order_value(self, stock_code: str, value: float,
                           side: str = 'long', strategy_id: Optional[str] = None) -> dict:
        """按指定金额下单。

        根据持仓最新价格计算可购买数量，并向下取整到整手。

        Args:
            stock_code: QMT格式的证券代码。
            value: 目标金额，正数为买入，负数为卖出。
            side: 方向，'long' 或 'short'，仅对期货生效。
            strategy_id: 策略ID，卖出时校验策略持仓可用数量。

        Returns:
            包含 order_id、direction、quantity、message 的字典。
        """
        price = _get_price(
            self.trader, self.account, stock_code,
            strategy_manager=self.strategy_manager, strategy_id=strategy_id,
        )
        target_qty = abs(value) / price
        quantity = _round_down_to_lot(target_qty, stock_code)

        # 策略级买入：按可用资金限制数量
        if strategy_id and self.strategy_manager is not None and value > 0:
            available_cash = self._get_strategy_available_cash(strategy_id)
            max_qty = _round_down_to_lot(available_cash / price, stock_code)
            quantity = min(quantity, max_qty)

        if quantity == 0:
            msg = f"下单金额不足以购买一手 (价值:{value:.2f}, 价格:{price:.2f})，订单取消"
            logger.warning(f"{YELLOW}【聚宽价值下单】{RESET} {stock_code} {msg}")
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': price,
                'order_type': None,
                'message': msg,
            }

        is_future = _is_future(stock_code)
        if is_future and side == 'short':
            order_type = STOCK_SELL if value > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if value > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        try:
            order_id = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            msg = (f"聚宽价值下单: {direction} {stock_code} {quantity}股 "
                   f"(价值:{value:.2f}, 价格:{price:.2f})")
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': quantity,
                'price': price,
                'order_type': order_type,
                'message': msg,
            }
        except Exception as e:
            msg = f"价值下单失败: {str(e)}"
            raise

    # ---- (4) jukuan_order_target_value ----

    def jukuan_order_target_value(self, stock_code: str, value: float,
                                  side: str = 'long', strategy_id: Optional[str] = None) -> dict:
        """按目标持仓市值调仓。

        计算当前持仓市值与目标市值的差值，并调用 jukuan_order_value 进行差额委托。

        Args:
            stock_code: QMT格式的证券代码。
            value: 目标持仓市值。
            side: 方向，'long' 或 'short'，仅对期货生效。
            strategy_id: 策略ID，卖出时校验策略持仓可用数量。

        Returns:
            包含 order_id、direction、quantity、message 的字典。
        """
        price = _get_price(
            self.trader, self.account, stock_code,
            strategy_manager=self.strategy_manager, strategy_id=strategy_id,
        )
        if strategy_id and self.strategy_manager is not None:
            current_qty = self._get_strategy_quantity(strategy_id, stock_code)
        else:
            current_qty = _get_volume(self.trader, self.account, stock_code)
        current_value = current_qty * price
        delta_value = value - current_value

        if abs(delta_value) < 0.01:
            msg = (f"目标价值已满足 (当前价值:{current_value:.2f}, 目标:{value:.2f})，"
                   f"不再调整")
            logger.info(f"{GREEN}【聚宽价值调仓】{RESET} {stock_code} {msg}")
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': price,
                'order_type': None,
                'message': msg,
            }

        return self.jukuan_order_value(
            stock_code, delta_value, side=side, strategy_id=strategy_id
        )
