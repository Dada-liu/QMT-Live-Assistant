"""QMT 连接看门狗。

负责维护 miniQMT 连接生命周期：
- 首次建立连接
- 监听 on_disconnected 回调并触发重连
- 周期性健康检查
- 指数退避重试
- 向 QMTServer 暴露连接状态
"""
import asyncio
import random
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Optional

from backend.qmt_client import create_trader, MyXtQuantTraderCallback
from backend.logger import logger

# watchdog 专用线程池：QMT 假死时，超时的 connect/健康检查线程无法强杀会泄漏，
# 用独立小池隔离，避免耗尽 asyncio 默认池饿死其他使用者（如 Bark 测试推送）。
_WATCHDOG_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="qmt-watchdog"
)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class _ReconnectAwareCallback(MyXtQuantTraderCallback):
    """继承默认交易回调，在 QMT 触发 on_disconnected 时通知 watchdog。

    xtquant 的回调可能运行在非 asyncio 线程，因此通过 loop.call_soon_threadsafe
    通知事件循环，避免线程安全问题。
    """

    def __init__(self, order_tracker=None, watchdog=None):
        super().__init__(order_tracker=order_tracker)
        self._watchdog = watchdog

    def on_disconnected(self):
        logger.warning("【QMT 连接断开】触发重连")
        if self._watchdog is not None:
            self._watchdog.request_reconnect()


class QMTConnectionWatchdog:
    """维护 QMT 连接，断开后自动重连。"""

    def __init__(
        self,
        account_id: str,
        qmt_path: str,
        order_tracker=None,
        health_check_interval: float = 5.0,
        health_check_timeout: float = 5.0,
        max_backoff: float = 60.0,
        connect_timeout: float = 30.0,
        stop_timeout: float = 10.0,
    ):
        self._account_id = account_id
        self._qmt_path = qmt_path
        self._order_tracker = order_tracker
        self._health_check_interval = health_check_interval
        self._health_check_timeout = health_check_timeout
        self._max_backoff = max_backoff
        self._connect_timeout = connect_timeout
        self._stop_timeout = stop_timeout

        self._state = ConnectionState.DISCONNECTED
        self._reconnect_failures = 0
        self._last_error: Optional[str] = None

        self._trader = None
        self._account = None
        self._callback: Optional[_ReconnectAwareCallback] = None

        self._watchdog_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._disconnect_signal: Optional[asyncio.Event] = None
        self._stop_signal: Optional[asyncio.Event] = None
        self._reconnect_lock: Optional[asyncio.Lock] = None
        self._running = False

    @property
    def state(self) -> str:
        return self._state.value

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_failures

    @property
    def trader(self):
        return self._trader

    @property
    def account(self):
        return self._account

    @property
    def callback(self):
        return self._callback

    def request_reconnect(self):
        """供回调线程安全调用，请求一次重连。"""
        if self._loop is not None and self._disconnect_signal is not None:
            try:
                self._loop.call_soon_threadsafe(self._disconnect_signal.set)
            except RuntimeError:
                pass

    async def start(self):
        """启动看门狗。会在当前事件循环中尝试首次连接并启动守护任务。"""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._disconnect_signal = asyncio.Event()
        self._stop_signal = asyncio.Event()
        self._reconnect_lock = asyncio.Lock()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self):
        """停止看门狗，关闭连接。"""
        self._running = False
        if self._stop_signal is not None:
            try:
                self._stop_signal.set()
            except RuntimeError:
                pass
        if self._disconnect_signal is not None:
            try:
                self._disconnect_signal.set()
            except RuntimeError:
                pass
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        await self._disconnect()
        self._set_state(ConnectionState.DISCONNECTED)

    async def _watchdog_loop(self):
        """主循环：连接、等待断开信号、健康检查、重连。"""
        try:
            while self._running:
                if self._state != ConnectionState.CONNECTED:
                    await self._attempt_connect()
                    if self._state != ConnectionState.CONNECTED:
                        await self._backoff_sleep()
                    continue

                try:
                    await asyncio.wait_for(
                        self._disconnect_signal.wait(),
                        timeout=self._health_check_interval,
                    )
                    self._disconnect_signal.clear()
                    if self._state == ConnectionState.CONNECTED:
                        self._set_state(ConnectionState.RECONNECTING)
                        self._last_error = "收到 QMT 断开回调"
                except asyncio.TimeoutError:
                    if not self._running:
                        break
                    if not await self._health_check():
                        if self._state == ConnectionState.CONNECTED:
                            self._set_state(ConnectionState.RECONNECTING)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"看门狗异常: {e}")

    async def _attempt_connect(self):
        """尝试建立连接。由锁保护，确保不会并发重连。"""
        async with self._reconnect_lock:
            if not self._running:
                return
            if self._state == ConnectionState.CONNECTED:
                return

            self._set_state(ConnectionState.CONNECTING)
            try:
                # 加超时：xtquant 的 start/connect 可能永久 hang，
                # 之前无超时时 watchdog 会永远停在 CONNECTING 且不再重试。
                # 注意：超时后底层线程无法强杀，若其最终连上会产生一个
                # 无人管理的僵尸连接，结果直接被丢弃，随进程退出回收。
                trader, account, callback = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        _WATCHDOG_EXECUTOR,
                        self._create_trader_sync,
                    ),
                    timeout=self._connect_timeout,
                )
                self._trader = trader
                self._account = account
                self._callback = callback

                # 连接建立后立即做一次健康检查，避免 trader 返回但已断开的情况被标记为 CONNECTED
                if not await self._health_check():
                    self._reconnect_failures += 1
                    self._last_error = self._last_error or "连接建立后健康检查失败"
                    self._set_state(ConnectionState.RECONNECTING)
                    logger.warning(
                        f"【QMT 连接失败】第 {self._reconnect_failures} 次尝试: {self._last_error}"
                    )
                    return

                self._reconnect_failures = 0
                self._last_error = None
                self._set_state(ConnectionState.CONNECTED)
                logger.info(f"【QMT 已连接】路径: {self._qmt_path}")
            except asyncio.TimeoutError:
                self._reconnect_failures += 1
                self._last_error = f"连接建立超时（{self._connect_timeout}s），miniQMT 可能无响应"
                self._set_state(ConnectionState.RECONNECTING)
                logger.warning(
                    f"【QMT 连接失败】第 {self._reconnect_failures} 次尝试: {self._last_error}"
                )
            except Exception as e:
                self._reconnect_failures += 1
                self._last_error = str(e)
                self._set_state(ConnectionState.RECONNECTING)
                logger.warning(
                    f"【QMT 连接失败】第 {self._reconnect_failures} 次尝试: {e}"
                )

    def _create_trader_sync(self):
        """同步包装 create_trader，便于在线程池中执行。"""
        callback = _ReconnectAwareCallback(
            order_tracker=self._order_tracker,
            watchdog=self,
        )
        return create_trader(
            self._account_id,
            self._qmt_path,
            order_tracker=self._order_tracker,
            callback=callback,
        )

    async def _health_check(self) -> bool:
        """轻量级健康检查。返回 True 表示连接正常。"""
        if self._trader is None or self._account is None:
            return False
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    _WATCHDOG_EXECUTOR,
                    self._trader.query_stock_asset,
                    self._account,
                ),
                timeout=self._health_check_timeout,
            )
            if self._last_error is not None and self._state == ConnectionState.CONNECTED:
                self._last_error = None
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"【QMT 健康检查失败】: {e}")
            return False

    async def _backoff_sleep(self):
        """按指数退避等待，可被 stop 中断。"""
        delay = min(2 ** self._reconnect_failures, self._max_backoff)
        delay = delay * (1 + random.random() * 0.2)
        try:
            await asyncio.wait_for(
                self._stop_signal.wait(),
                timeout=delay,
            )
        except asyncio.TimeoutError:
            pass

    async def _disconnect(self):
        """清理当前连接引用，可选停止旧 trader。"""
        try:
            old_trader = self._trader
            self._trader = None
            self._account = None
            self._callback = None
            if old_trader is not None and hasattr(old_trader, "stop"):
                # 加超时：trader.stop 可能 hang，之前无超时时
                # /api/stop-server 与 lifespan 关停会永久挂起
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        _WATCHDOG_EXECUTOR,
                        old_trader.stop,
                    ),
                    timeout=self._stop_timeout,
                )
        except asyncio.TimeoutError:
            logger.warning(
                f"停止旧 trader 超时（{self._stop_timeout}s），放弃等待继续清理"
            )
        except Exception as e:
            logger.warning(f"停止旧 trader 时出错: {e}")

    def _set_state(self, state: ConnectionState):
        if self._state != state:
            self._state = state
            logger.info(f"【连接状态】{state.value}")
