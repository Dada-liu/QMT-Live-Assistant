from collections import deque
from datetime import datetime
from typing import Optional

from backend.qmt_client import jq_to_qmt, qmt_to_jq
from backend.logger import logger
from backend.constants import GREEN, BLUE, YELLOW, RESET, STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import LATEST_PRICE

FUTURE_EXCHANGES = {'.CCFX', '.XDCE', '.XSGE', '.XZCE'}


def _is_future(code: str) -> bool:
    for suffix in FUTURE_EXCHANGES:
        if code.endswith(suffix):
            return True
    return False


def _lot_size(code: str) -> int:
    return 1 if _is_future(code) else 100


def _round_down_to_lot(quantity: float, code: str) -> int:
    size = _lot_size(code)
    return int(quantity / size) * size


def _get_position_info(trader, account, jq_code: str) -> dict:
    qmt_code = jq_to_qmt(jq_code)
    try:
        positions = trader.query_stock_positions(account)
    except Exception:
        positions = []

    for pos in positions:
        pos_code = getattr(pos, 'stock_code', '')
        if pos_code != qmt_code:
            continue
        return {
            'volume': getattr(pos, 'volume', 0) or getattr(pos, 'amount', 0) or 0,
            'price': getattr(pos, 'last_price', 0.0) or getattr(pos, 'price', 0.0) or 0.0,
            'found': True,
        }

    return {'volume': 0, 'price': 0.0, 'found': False}


def _get_price(trader, account, jq_code: str) -> float:
    info = _get_position_info(trader, account, jq_code)
    if info['price'] > 0:
        return info['price']
    raise ValueError(f"无法获取 {jq_code} 的最新价格，请确保持仓中有该股票或先买入少量")


def _get_volume(trader, account, jq_code: str) -> int:
    info = _get_position_info(trader, account, jq_code)
    return info['volume']


class JukuanOrderHandler:
    def __init__(self, trader, account, signal_log: deque = None,
                 strategy_manager=None):
        self.trader = trader
        self.account = account
        self.signal_log = signal_log
        self.strategy_manager = strategy_manager

    def _submit_order(self, jq_code: str, order_type: int, quantity: int,
                      strategy_name: str = 'jukuan_order') -> int:
        qmt_code = jq_to_qmt(jq_code)
        order_id = self.trader.order_stock(
            self.account,
            stock_code=qmt_code,
            order_type=order_type,
            order_volume=quantity,
            price_type=LATEST_PRICE,
            price=0,
            strategy_name=strategy_name,
            order_remark=jq_code,
        )
        logger.info(
            f"{BLUE}【聚宽下单】{RESET} "
            f"股票:{jq_code}→{qmt_code} "
            f"类型:{'买入' if order_type == STOCK_BUY else '卖出'} "
            f"数量:{quantity} "
            f"订单编号:{order_id}"
        )
        return order_id

    def _log_signal(self, jq_code: str, direction: str, quantity: int,
                    order_id: Optional[int], status: str, message: str,
                    strategy_name: str = 'jukuan_order'):
        if self.signal_log is not None:
            self.signal_log.append({
                'type': 'jukuan_order',
                'stock_code': jq_code,
                'direction': direction,
                'quantity': quantity,
                'order_id': str(order_id) if order_id else None,
                'status': status,
                'timestamp': datetime.now().isoformat(),
                'strategy_name': strategy_name,
                'message': message,
            })

    # ---- (1) jukuan_order ----

    def jukuan_order(self, security: str, amount: int,
                     side: str = 'long') -> dict:
        is_future = _is_future(security)
        quantity = _round_down_to_lot(abs(amount), security)

        if quantity == 0:
            msg = f"下单数量不足一手，调整为0股，订单取消"
            logger.warning(f"{YELLOW}【聚宽下单】{RESET} {security} {msg}")
            self._log_signal(security, 'none', 0, None, 'cancelled', msg)
            return {'order_id': None, 'direction': 'none', 'quantity': 0, 'message': msg}

        if is_future and side == 'short':
            order_type = STOCK_SELL if amount > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if amount > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        try:
            order_id = self._submit_order(security, order_type, quantity)
            msg = f"聚宽下单: {direction} {security} {quantity}股"
            self._log_signal(security, direction, quantity, order_id,
                             'submitted', msg)
            return {'order_id': order_id, 'direction': direction, 'quantity': quantity, 'message': msg}
        except Exception as e:
            msg = f"下单失败: {str(e)}"
            self._log_signal(security, direction, quantity, None,
                             'failed', msg)
            raise

    # ---- (2) jukuan_order_target ----

    def jukuan_order_target(self, security: str, amount: int,
                            side: str = 'long') -> dict:
        current_qty = _get_volume(self.trader, self.account, security)
        delta = amount - current_qty

        if delta == 0:
            msg = f"目标数量已满足 (当前:{current_qty}, 目标:{amount})，不再调整"
            logger.info(f"{GREEN}【聚宽调仓】{RESET} {security} {msg}")
            self._log_signal(security, 'none', 0, None, 'skipped', msg)
            return {'order_id': None, 'direction': 'none', 'quantity': 0, 'message': msg}

        is_future = _is_future(security)
        quantity = _round_down_to_lot(abs(delta), security)

        if quantity == 0:
            msg = f"调整数量不足一手 (delta:{delta})，订单取消"
            logger.warning(f"{YELLOW}【聚宽调仓】{RESET} {security} {msg}")
            self._log_signal(security, 'none', 0, None, 'cancelled', msg)
            return {'order_id': None, 'direction': 'none', 'quantity': 0, 'message': msg}

        if is_future and side == 'short':
            order_type = STOCK_SELL if delta > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if delta > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        try:
            order_id = self._submit_order(security, order_type, quantity)
            msg = f"聚宽调仓: {direction} {security} {quantity}股 (当前:{current_qty}→目标:{amount})"
            self._log_signal(security, direction, quantity, order_id,
                             'submitted', msg)
            return {'order_id': order_id, 'direction': direction, 'quantity': quantity, 'message': msg}
        except Exception as e:
            msg = f"调仓失败: {str(e)}"
            self._log_signal(security, direction, quantity, None,
                             'failed', msg)
            raise

    # ---- (3) jukuan_order_value ----

    def jukuan_order_value(self, security: str, value: float,
                           side: str = 'long') -> dict:
        price = _get_price(self.trader, self.account, security)
        target_qty = abs(value) / price
        quantity = _round_down_to_lot(target_qty, security)

        if quantity == 0:
            msg = f"下单金额不足以购买一手 (价值:{value:.2f}, 价格:{price:.2f})，订单取消"
            logger.warning(f"{YELLOW}【聚宽价值下单】{RESET} {security} {msg}")
            self._log_signal(security, 'none', 0, None, 'cancelled', msg)
            return {'order_id': None, 'direction': 'none', 'quantity': 0, 'message': msg}

        is_future = _is_future(security)
        if is_future and side == 'short':
            order_type = STOCK_SELL if value > 0 else STOCK_BUY
        else:
            order_type = STOCK_BUY if value > 0 else STOCK_SELL

        direction = 'buy' if order_type == STOCK_BUY else 'sell'

        try:
            order_id = self._submit_order(security, order_type, quantity)
            msg = (f"聚宽价值下单: {direction} {security} {quantity}股 "
                   f"(价值:{value:.2f}, 价格:{price:.2f})")
            self._log_signal(security, direction, quantity, order_id,
                             'submitted', msg)
            return {'order_id': order_id, 'direction': direction, 'quantity': quantity, 'message': msg}
        except Exception as e:
            msg = f"价值下单失败: {str(e)}"
            self._log_signal(security, direction, quantity, None,
                             'failed', msg)
            raise

    # ---- (4) jukuan_order_target_value ----

    def jukuan_order_target_value(self, security: str, value: float,
                                  side: str = 'long') -> dict:
        price = _get_price(self.trader, self.account, security)
        current_qty = _get_volume(self.trader, self.account, security)
        current_value = current_qty * price
        delta_value = value - current_value

        if abs(delta_value) < 0.01:
            msg = (f"目标价值已满足 (当前价值:{current_value:.2f}, 目标:{value:.2f})，"
                   f"不再调整")
            logger.info(f"{GREEN}【聚宽价值调仓】{RESET} {security} {msg}")
            self._log_signal(security, 'none', 0, None, 'skipped', msg)
            return {'order_id': None, 'direction': 'none', 'quantity': 0, 'message': msg}

        return self.jukuan_order_value(security, delta_value, side=side)
