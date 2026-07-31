"""Bark 推送编排服务。

读取全局 Bark 配置，结合策略级开关决定是否推送；
所有推送均在 daemon 线程中异步发出，不阻塞订单状态机。
"""
import threading
from datetime import datetime, timezone
from typing import Callable, List, Optional

from pydantic import BaseModel, Field

from backend import bark_notifier
from backend.bark_notifier import DEFAULT_SERVER_URL, FAILED_SOUND, LEVEL_CRITICAL
from backend.db.repositories.settings import InMemorySettingsRepository, SettingsRepository
from backend.logger import logger
from backend.models.order import OrderState, TrackedOrder

BARK_SETTINGS_KEY = "bark"


class BarkConfig(BaseModel):
    """Bark 全局推送配置。"""

    enabled: bool = False
    device_key: str = ""
    server_url: str = DEFAULT_SERVER_URL
    stale_minutes: int = Field(default=5, gt=0)


class BarkService:
    """Bark 推送编排：配置持久化 + 事件门控 + 后台发送。"""

    def __init__(
        self,
        settings_repo: Optional[SettingsRepository] = None,
        strategy_lookup: Optional[Callable[[Optional[str]], bool]] = None,
    ):
        self._repo = settings_repo or InMemorySettingsRepository()
        self._strategy_lookup = strategy_lookup or (lambda strategy_id: True)
        self._config: BarkConfig = self._load_config()
        self._stale_notified: set[str] = set()

    def get_config(self) -> BarkConfig:
        return self._config

    def update_config(self, config: BarkConfig) -> BarkConfig:
        """持久化并热更新配置（整体替换引用，保证线程读到一致快照）。"""
        self._repo.set(BARK_SETTINGS_KEY, config.model_dump_json())
        self._config = config
        return config

    def send_test(self, config: Optional[BarkConfig] = None) -> bool:
        """同步发送一条测试推送用于验证绑定，失败返回 False。"""
        cfg = config or self._config
        if not cfg.device_key:
            logger.warning("Bark 测试推送失败: 未配置 device_key")
            return False
        title, body = bark_notifier.build_test_message()
        return bark_notifier.send_push(cfg.server_url, cfg.device_key, title, body)

    def notify_placed(self, order: TrackedOrder) -> None:
        """订单发起事件（普通级别）。"""
        if not self._gate(order):
            return
        title, body = bark_notifier.build_placed_message(order)
        self._spawn(title, body)

    def notify_terminal(self, order: TrackedOrder) -> None:
        """订单终态事件：成交为普通级别；失败为 critical + 铃声。"""
        self._stale_notified.discard(order.order_id)
        if not self._gate(order):
            return
        title, body = bark_notifier.build_terminal_message(order)
        if order.status == OrderState.FAILED:
            self._spawn(title, body, level=LEVEL_CRITICAL, sound=FAILED_SOUND)
        else:
            self._spawn(title, body)

    def check_stale_orders(
        self,
        pending_orders: List[TrackedOrder],
        now: Optional[datetime] = None,
    ) -> None:
        """检查超龄未成交订单并提醒（critical 级别），每笔订单仅提醒一次。"""
        now = now or datetime.now(timezone.utc)
        stale_seconds = self._config.stale_minutes * 60
        pending_ids = set()
        for order in pending_orders:
            pending_ids.add(order.order_id)
            if order.order_id in self._stale_notified:
                continue
            placed_at = order.placed_at
            if placed_at.tzinfo is None:
                # DB 读回的 placed_at 无时区信息，按 UTC 解释
                placed_at = placed_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - placed_at).total_seconds()
            if age_seconds < stale_seconds:
                continue
            if not self._gate(order):
                continue
            self._stale_notified.add(order.order_id)
            title, body = bark_notifier.build_stale_message(order, int(age_seconds // 60))
            self._spawn(title, body, level=LEVEL_CRITICAL)
        # 清理已离开 pending 的订单 id，避免集合无限增长
        self._stale_notified.intersection_update(pending_ids)

    def _gate(self, order: TrackedOrder) -> bool:
        """全局开关 + device_key + 策略级开关，三者同时满足才推送。"""
        config = self._config
        if not config.enabled or not config.device_key:
            return False
        try:
            return self._strategy_lookup(order.strategy_id)
        except Exception as e:
            # 门控运行在订单状态机回调链上，查询异常不应中断状态机
            logger.error(f"Bark 策略开关查询失败，默认放行: {e}")
            return True

    def _spawn(
        self,
        title: str,
        body: str,
        level: Optional[str] = None,
        sound: Optional[str] = None,
    ) -> None:
        """在 daemon 线程中发送推送，避免阻塞调用方线程。"""
        config = self._config  # 快照，避免发送期间配置被替换导致不一致
        thread = threading.Thread(
            target=bark_notifier.send_push,
            args=(config.server_url, config.device_key, title, body),
            kwargs={"level": level, "sound": sound},
            daemon=True,
        )
        thread.start()

    def _load_config(self) -> BarkConfig:
        raw = self._repo.get(BARK_SETTINGS_KEY)
        if not raw:
            return BarkConfig()
        try:
            return BarkConfig.model_validate_json(raw)
        except Exception as e:
            logger.error(f"Bark 配置解析失败，回退默认配置: {e}")
            return BarkConfig()
