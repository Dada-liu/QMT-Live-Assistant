"""聚宽风格下单处理器。

提供聚宽 API 风格的下单方法（order/order_target/order_value/order_target_value），
支持证券代码自动转换、按手数取整、期货空头处理，以及无持仓时行情取价。
"""
from typing import Optional
from backend.utils import (
    fetch_latest_prices_from_xtdata,
    qmt_to_jq,
    qmt_call,
    is_market_price_type,
    price_type_name,
    validate_price_type_for_market,
    MARKET_PRICE_TYPE_SET,
    is_future,
    is_convertible_bond,
    get_lot_size,
    get_quantity_unit,
    validate_security_type_for_strategy,
)
from backend.qmt_client import create_trader
from backend.logger import logger
from backend.constants import (
    GREEN, BLUE, YELLOW, RED, RESET, STOCK_BUY, STOCK_SELL,
    INSUFFICIENT_FUNDS_REJECT, INSUFFICIENT_FUNDS_MAX_BUYABLE,
)
from backend.qmt_xtconstant import LATEST_PRICE, FIX_PRICE, ORDER_TYPE_SET, PRICE_TYPE_SET

# 兼容旧导入路径：_is_future 已迁移至 backend.utils.is_future
_is_future = is_future


class InsufficientFundsError(ValueError):
    """策略可用资金不足（reject 策略）。

    子类化 ValueError 以保持现有异常处理路径不变；
    端点可单独捕获它实现"挂起等待卖出成交"的延迟买单逻辑。
    """


def _lot_size(code: str) -> int:
    """获取证券每手数量：期货 1，可转债 10（张），股票 100（股）。"""
    return get_lot_size(code)


def _round_down_to_lot(quantity: float, code: str) -> int:
    """将下单数量向下取整到最近手数倍，避免非整手委托。"""
    size = _lot_size(code)
    return int(quantity / size) * size


def _get_position_info(trader, account, stock_code: str) -> dict:
    """查询指定 QMT 代码在账户中的持仓信息。

    返回包含持仓数量、参考价格以及是否找到持仓的字典。
    """
    try:
        positions = qmt_call(
            trader,
            "query_stock_positions",
            account,
            context={"stock_code": stock_code, "account_id": getattr(account, 'account_id', account)},
        )
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

    def _cap_quantity_by_funds_policy(self, strategy_id: Optional[str], stock_code: str,
                                      direction: str, quantity: int, freeze_price: float) -> int:
        """按策略的资金不足处理策略调整买入数量。

        仅当策略配置为 max_buyable 且买入成本超出可用资金时，将数量封顶到
        可用资金可负担的最大整手数；其余情况原样返回。返回 0 表示一手都买不起。
        """
        if direction != 'buy' or not strategy_id or self.strategy_manager is None:
            return quantity
        if freeze_price <= 0:
            return quantity
        strategy = self.strategy_manager.get(strategy_id)
        if strategy is None:
            return quantity
        policy = getattr(strategy, 'insufficient_funds_policy', INSUFFICIENT_FUNDS_REJECT)
        if policy != INSUFFICIENT_FUNDS_MAX_BUYABLE:
            return quantity
        if quantity * freeze_price <= strategy.available_cash:
            return quantity
        capped = _round_down_to_lot(strategy.available_cash / freeze_price, stock_code)
        logger.warning(
            f"{YELLOW}【聚宽下单】{RESET} {stock_code} 可用资金不足，"
            f"按策略配置调整为最大可买数量: {quantity} → {capped}"
        )
        return capped

    def _submit_order(self, stock_code: str, order_type: int, quantity: int,
                      price: float = 0.0,
                      price_type: Optional[int] = None,
                      strategy_name: str = 'jukuan_order',
                      strategy_id: Optional[str] = None,
                      order_remark: Optional[str] = None) -> dict:
        """向QMT提交一笔委托，返回包含订单编号与乐观冻结快照的字典。

        在调用 QMT 下单接口之前，先通过 strategy_manager 完成资金/持仓的
        乐观冻结，使校验与占用成为原子步骤，避免并发请求出现可用资金被重复扣减。

        Args:
            stock_code: QMT格式的证券代码。
            order_type: 委托类型（买入或卖出）。
            quantity: 委托数量，已按手数取整。
            price: 参考价格，用于乐观冻结与策略级资金校验。
            price_type: 显式报价类型；None 时由 price 推导。
            strategy_name: 策略名称，写入QMT订单备注。
            strategy_id: 策略ID，用于校验并冻结策略持仓/资金。
            order_remark: 自定义订单备注；None 时使用聚宽格式代码。

        Returns:
            包含 order_id（QMT返回的订单编号）和 optimistic_snapshot
            （乐观冻结快照，用于后续 reconcile / rollback）的字典。
        """
        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        # 报价类型校验与派生先于资金冻结，fail-fast；
        # 市价场景（price<=0 且未显式指定）使用策略配置的默认市价方式
        validate_price_type_for_market(stock_code, price_type)
        # 券种强校验：策略种类（股票/可转债）与证券代码券种必须一致
        validate_security_type_for_strategy(
            self._get_strategy_security_type(strategy_id), stock_code
        )
        unit = get_quantity_unit(stock_code)
        if price_type is not None:
            final_price_type = price_type
        elif price > 0:
            final_price_type = FIX_PRICE
        else:
            final_price_type = self._get_strategy_market_price_type(strategy_id)

        # 市价买入单（price=0 或市价报价类型）没有委托价可冻结，用最新价估算成本做校验与冻结；
        # 行情取价失败时 freeze_price=0，成本为 0 视为跳过校验，由 QMT 实盘兜底
        freeze_price = price
        if (direction == 'buy'
                and (price <= 0 or is_market_price_type(final_price_type))
                and strategy_id and self.strategy_manager is not None):
            freeze_price = fetch_latest_prices_from_xtdata([stock_code]).get(stock_code, 0.0)

        # 策略配置为 max_buyable 时，买入数量先按可用资金封顶；封顶为 0 说明一手都买不起，订单取消
        requested_quantity = quantity
        quantity = self._cap_quantity_by_funds_policy(
            strategy_id, stock_code, direction, quantity, freeze_price
        )
        funds_cap_note = None
        if direction == 'buy' and quantity < requested_quantity:
            funds_cap_note = (
                f"策略可用资金不足，按最大可买数量下单: "
                f"请求 {requested_quantity} {unit}, 实际下单 {quantity} {unit}"
            )
        if direction == 'buy' and quantity == 0:
            msg = f"策略可用资金不足一手，订单取消: {stock_code} (请求 {requested_quantity} {unit})"
            logger.warning(f"{YELLOW}【聚宽下单】{RESET} {msg}")
            return {
                'order_id': None,
                'optimistic_snapshot': None,
                'quantity': 0,
                'price_type': None,
                'cancelled': True,
                'message': msg,
                'requested_quantity': requested_quantity,
                'funds_cap_note': msg,
            }

        # 先原子性地冻结资金/持仓；返回 None 说明资金或持仓不足
        optimistic_snapshot = None
        if strategy_id and self.strategy_manager is not None:
            optimistic_snapshot = self.strategy_manager.apply_optimistic_position(
                strategy_id, stock_code, direction, quantity, freeze_price
            )
            if optimistic_snapshot is None:
                if direction == 'buy':
                    available_cash = self._get_strategy_available_cash(strategy_id)
                    cost = quantity * freeze_price
                    raise InsufficientFundsError(
                        f"策略可用资金不足: {stock_code} 需要 {cost:.2f}, 可用 {available_cash:.2f}"
                    )
                else:
                    available = self._get_strategy_available_quantity(strategy_id, stock_code)
                    raise ValueError(
                        f"策略可用持仓不足: {stock_code} 可用 {available} {unit}, 需要卖出 {quantity} {unit}"
                    )

        order_price = price if final_price_type == FIX_PRICE else 0

        jq_code = qmt_to_jq(stock_code)
        actual_remark = order_remark if order_remark is not None else jq_code
        try:
            order_id = qmt_call(
                self.trader,
                "order_stock",
                self.account,
                stock_code=stock_code,
                order_type=order_type,
                order_volume=quantity,
                price_type=final_price_type,
                price=order_price,
                strategy_name=strategy_name,
                order_remark=actual_remark,
                context={
                    "stock_code": stock_code,
                    "order_type": order_type,
                    "quantity": quantity,
                    "price_type": final_price_type,
                    "price": order_price,
                    "strategy_name": strategy_name,
                },
            )
        except Exception as e:
            logger.error(f"{RED}【聚宽下单】{RESET} {stock_code} 下单失败: {e}")
            # QMT 下单失败时回滚已冻结的资金/持仓
            if optimistic_snapshot is not None:
                self.strategy_manager.rollback_position(strategy_id, optimistic_snapshot)
            raise

        if not order_id:
            if optimistic_snapshot is not None:
                self.strategy_manager.rollback_position(strategy_id, optimistic_snapshot)
            raise ValueError("QMT 下单失败，返回空订单号")

        logger.info(
            f"{BLUE}【聚宽下单】{RESET} "
            f"证券:{jq_code}→{stock_code} "
            f"类型:{'买入' if order_type == STOCK_BUY else '卖出'} "
            f"数量:{quantity}{unit} "
            f"价格类型:{price_type_name(final_price_type)} "
            f"价格:{order_price:.2f} "
            f"订单编号:{order_id}"
        )
        return {
            'order_id': order_id,
            'optimistic_snapshot': optimistic_snapshot,
            'quantity': quantity,
            'price_type': final_price_type,
            'requested_quantity': requested_quantity,
            'funds_cap_note': funds_cap_note,
        }

    def _get_strategy_security_type(self, strategy_id: Optional[str]) -> Optional[str]:
        """读取策略种类（stock/convertible_bond）；无策略或未设置时返回 None（跳过券种校验）。"""
        if not strategy_id or self.strategy_manager is None:
            return None
        strategy = self.strategy_manager.get(strategy_id)
        if strategy is None:
            return None
        return getattr(strategy, 'security_type', None)

    def _get_strategy_market_price_type(self, strategy_id: Optional[str]) -> int:
        """读取策略配置的默认市价下单方式；未配置或策略不存在时回退最新价。"""
        if not strategy_id or self.strategy_manager is None:
            return LATEST_PRICE
        strategy = self.strategy_manager.get(strategy_id)
        if strategy is None:
            return LATEST_PRICE
        value = getattr(strategy, 'default_market_price_type', None)
        if value in MARKET_PRICE_TYPE_SET:
            return value
        return LATEST_PRICE

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
            msg = f"下单数量不足一手，调整为0{get_quantity_unit(stock_code)}，订单取消"
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
            submit_result = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            if submit_result.get('cancelled'):
                return {
                    'order_id': None,
                    'stock_code': stock_code,
                    'jq_code': qmt_to_jq(stock_code),
                    'direction': 'none',
                    'quantity': 0,
                    'price': price,
                    'order_type': None,
                    'requested_quantity': submit_result['requested_quantity'],
                    'funds_cap_note': submit_result['funds_cap_note'],
                    'cancelled': True,
                    'message': submit_result['message'],
                }
            order_id = submit_result['order_id']
            optimistic_snapshot = submit_result.get('optimistic_snapshot')
            actual_quantity = submit_result['quantity']
            msg = f"聚宽下单: {direction} {stock_code} {actual_quantity}{get_quantity_unit(stock_code)}"
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': actual_quantity,
                'price': price,
                'price_type': submit_result['price_type'],
                'order_type': order_type,
                'requested_quantity': submit_result['requested_quantity'],
                'funds_cap_note': submit_result['funds_cap_note'],
                'optimistic_snapshot': optimistic_snapshot,
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
            submit_result = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            if submit_result.get('cancelled'):
                return {
                    'order_id': None,
                    'stock_code': stock_code,
                    'jq_code': qmt_to_jq(stock_code),
                    'direction': 'none',
                    'quantity': 0,
                    'price': price,
                    'order_type': None,
                    'requested_quantity': submit_result['requested_quantity'],
                    'funds_cap_note': submit_result['funds_cap_note'],
                    'cancelled': True,
                    'message': submit_result['message'],
                }
            order_id = submit_result['order_id']
            optimistic_snapshot = submit_result.get('optimistic_snapshot')
            actual_quantity = submit_result['quantity']
            msg = f"聚宽调仓: {direction} {stock_code} {actual_quantity}{get_quantity_unit(stock_code)} (当前:{current_qty}→目标:{amount})"
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': actual_quantity,
                'price': price,
                'price_type': submit_result['price_type'],
                'order_type': order_type,
                'requested_quantity': submit_result['requested_quantity'],
                'funds_cap_note': submit_result['funds_cap_note'],
                'optimistic_snapshot': optimistic_snapshot,
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
                'price_type': None,
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
            submit_result = self._submit_order(
                stock_code, order_type, quantity, price=price, strategy_id=strategy_id
            )
            if submit_result.get('cancelled'):
                return {
                    'order_id': None,
                    'stock_code': stock_code,
                    'jq_code': qmt_to_jq(stock_code),
                    'direction': 'none',
                    'quantity': 0,
                    'price': price,
                    'order_type': None,
                    'requested_quantity': submit_result['requested_quantity'],
                    'funds_cap_note': submit_result['funds_cap_note'],
                    'cancelled': True,
                    'message': submit_result['message'],
                }
            order_id = submit_result['order_id']
            optimistic_snapshot = submit_result.get('optimistic_snapshot')
            actual_quantity = submit_result['quantity']
            msg = (f"聚宽价值下单: {direction} {stock_code} {actual_quantity}{get_quantity_unit(stock_code)} "
                   f"(价值:{value:.2f}, 价格:{price:.2f})")
            return {
                'order_id': order_id,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': direction,
                'quantity': actual_quantity,
                'price': price,
                'price_type': submit_result['price_type'],
                'order_type': order_type,
                'requested_quantity': submit_result['requested_quantity'],
                'funds_cap_note': submit_result['funds_cap_note'],
                'optimistic_snapshot': optimistic_snapshot,
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
                'price_type': None,
                'order_type': None,
                'message': msg,
            }

        return self.jukuan_order_value(
            stock_code, delta_value, side=side, strategy_id=strategy_id
        )

    # ---- (5) generic_order ----

    def generic_order(
        self,
        stock_code: str,
        quantity: int,
        direction: str = 'buy',
        price: float = 0.0,
        price_type: Optional[int] = None,
        order_type: Optional[int] = None,
        strategy_name: str = 'generic_order',
        strategy_id: Optional[str] = None,
        order_remark: Optional[str] = None,
    ) -> dict:
        """通用下单接口，暴露完整业务层委托参数。

        支持通过 direction 或显式 order_type 指定委托类型，支持显式 price_type
        或根据 price 推导。买入股票时会校验整手（期货除外）。

        Args:
            stock_code: QMT格式的证券代码。
            quantity: 委托数量。
            direction: 下单方向，'buy' 或 'sell'；与 order_type 二选一。
            price: 委托价格，0 表示市价/最新价。
            price_type: 显式报价类型；None 时由 price 推导。
            order_type: 显式 xtquant 委托类型；None 时由 direction 推导。
            strategy_name: 策略名称，写入QMT订单备注。
            strategy_id: 策略ID，用于乐观冻结。
            order_remark: 自定义订单备注；None 时使用聚宽格式代码。

        Returns:
            包含 order_id、direction、quantity、price、price_type、order_type、
            optimistic_snapshot、message 的字典。
        """
        if direction not in ('buy', 'sell'):
            raise ValueError("direction 必须为 buy 或 sell")

        if order_type is None:
            final_order_type = STOCK_BUY if direction == 'buy' else STOCK_SELL
        else:
            if order_type not in ORDER_TYPE_SET:
                raise ValueError(f"不支持的 order_type: {order_type}")
            final_order_type = order_type

        if price_type is not None and price_type not in PRICE_TYPE_SET:
            raise ValueError(f"不支持的 price_type: {price_type}")

        # 买入须为整手（股票 100 股、可转债 10 张；期货除外）
        lot_size = get_lot_size(stock_code)
        if (final_order_type == STOCK_BUY
                and not is_future(stock_code)
                and quantity % lot_size != 0):
            unit = get_quantity_unit(stock_code)
            if is_convertible_bond(stock_code):
                raise ValueError(
                    f"可转债买入数量须为10的整数倍: {stock_code} 请求 {quantity} {unit}"
                )
            raise ValueError(
                f"股票买入数量须为100的整数倍: {stock_code} 请求 {quantity} {unit}"
            )

        submit_result = self._submit_order(
            stock_code=stock_code,
            order_type=final_order_type,
            quantity=quantity,
            price=price,
            price_type=price_type,
            strategy_name=strategy_name,
            strategy_id=strategy_id,
            order_remark=order_remark,
        )

        if submit_result.get('cancelled'):
            return {
                'order_id': None,
                'stock_code': stock_code,
                'jq_code': qmt_to_jq(stock_code),
                'direction': 'none',
                'quantity': 0,
                'price': price,
                'price_type': None,
                'order_type': None,
                'requested_quantity': submit_result['requested_quantity'],
                'funds_cap_note': submit_result['funds_cap_note'],
                'cancelled': True,
                'optimistic_snapshot': None,
                'strategy_name': strategy_name,
                'message': submit_result['message'],
            }

        final_price_type = submit_result['price_type']

        actual_quantity = submit_result['quantity']
        msg = f"通用下单: {direction} {stock_code} {actual_quantity}{get_quantity_unit(stock_code)}"
        return {
            'order_id': submit_result['order_id'],
            'stock_code': stock_code,
            'jq_code': qmt_to_jq(stock_code),
            'direction': direction,
            'quantity': actual_quantity,
            'price': price,
            'price_type': final_price_type,
            'order_type': final_order_type,
            'requested_quantity': submit_result['requested_quantity'],
            'funds_cap_note': submit_result['funds_cap_note'],
            'optimistic_snapshot': submit_result.get('optimistic_snapshot'),
            'strategy_name': strategy_name,
            'message': msg,
        }
