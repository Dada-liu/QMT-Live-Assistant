# Phase 4：可靠性加固计划

> 本文档依据 `reconstruction-doc/THINKING.md` 制定，目标是将系统从「能跑」升级为「7×24 稳定运行」：QMT 断连自动重连、订单处理队列化、操作审计、多渠道告警。

---

## 一、目标与范围

### 1.1 核心目标

1. **QMT 断连自动重连**：检测到 QMT 连接断开后，按指数退避策略自动重连。
2. **订单处理队列化**：远程信号进入队列，顺序处理，避免高并发下丢单或状态竞争。
3. **操作审计日志**：记录所有关键操作（登录、启停服务、创建/删除策略、下单、撤单、修改配置）。
4. **多渠道告警**：支持企业微信、钉钉、飞书机器人推送异常告警。
5. **健康检查**：提供 `/health` 详细状态，包括 QMT 连接状态、队列积压、最近错误。

### 1.2 本次不做

- 主备高可用架构
- 云端信号中继
- 完整 SLA 监控面板（仅提供基础 health endpoint）
- 自动故障转移（先做单机自动恢复）

### 1.3 验收标准

- [ ] 手动断开 QMT 后，系统能在 30 秒内检测到断连，并在 1-5 分钟内自动恢复。
- [ ] 重连后 pending 订单能继续跟踪，未完成订单可重新订阅回调。
- [ ] 并发发送 100 个信号，所有订单都被处理且无重复/丢失。
- [ ] 所有管理操作和下单操作写入 `audit_logs`。
- [ ] 配置的告警渠道能在异常时收到消息（企业微信/钉钉/飞书至少一种）。
- [ ] `/health` 返回 QMT 连接状态、队列长度、最近错误时间。
- [ ] 现有 171 个 pytest 用例通过，新增可靠性测试覆盖核心路径。

---

## 二、现状分析

### 2.1 当前连接处理

`backend/qmt_client.py`：

```python
class MyXtQuantTraderCallback:
    def on_disconnected(self):
        logger.warning(f"{YELLOW}【连接断开】{RESET}")

def create_trader(account_id, mini_qmt_path, order_tracker=None):
    # ...
    connect_result = xt_trader.connect()
    if is_real_xtquant:
        if connect_result == 0:
            logger.debug("连接成功")
        else:
            raise ConnectionError(...)
    # ...
    return xt_trader, account, callback
```

**问题**：`on_disconnected` 只打印日志，无自动重连逻辑。

### 2.2 当前订单处理

`backend/server.py`：

```python
async def _jukuan_endpoint(request: dict, x_token: str, method_name: str):
    # 直接调用 handler 方法下单
    result = method(qmt_code, amount, side=side)
    # 跟踪订单
    ...
```

**问题**：信号处理是同步的，高并发时可能：

- 多个信号同时修改同一策略持仓，产生竞争。
- 下单失败时直接抛出异常，信号丢失。
- 无重试机制。

### 2.3 当前告警

`backend/logger.py` 已有 `WeChatHandler`，但：

- 只有企业微信。
- 所有 INFO 级别日志都推送，噪音大。
- 无钉钉/飞书支持。

### 2.4 当前审计

无系统化的审计日志，仅有操作日志分散在 `logger.py`。

---

## 三、目标架构

```
backend/
├── reliability/
│   ├── __init__.py
│   ├── connection_manager.py   # QMT 连接管理 + 自动重连
│   ├── order_queue.py          # 订单处理队列
│   ├── auditor.py              # 审计日志写入
│   └── alerter.py              # 多渠道告警
├── services/
│   └── account_service.py      # 使用 ConnectionManager
└── routers/
    └── health.py               # /health 详细状态
```

---

## 四、设计原则

1. **故障自愈优先**：单机环境下，自动重连和队列补偿比主备架构更经济。
2. **异步解耦**：信号接收和实际下单通过队列解耦，提高吞吐量并避免阻塞。
3. **幂等性**：队列中的信号处理必须幂等，防止重连或重试导致重复下单。
4. **可观测性**：health endpoint 暴露关键运行指标。
5. **告警分级**：错误/断连等关键事件才告警，避免日志噪音。

---

## 五、实施步骤

### Step 1：QMT 连接管理与自动重连（2-3 天）

#### 1.1 封装 `ConnectionManager`

`backend/reliability/connection_manager.py`：

```python
import asyncio
import random
from enum import Enum

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"

class ConnectionManager:
    def __init__(self, account_service, max_retries=10,
                 base_delay=1.0, max_delay=60.0):
        self._account_service = account_service
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._state = ConnectionState.DISCONNECTED
        self._retry_count = 0
        self._last_disconnect_at = None
        self._last_error = None
        self._reconnect_task = None

    @property
    def state(self) -> ConnectionState:
        return self._state

    async def connect(self, account_id: str, mini_qmt_path: str) -> None:
        self._state = ConnectionState.CONNECTING
        try:
            self._account_service.connect(account_id, mini_qmt_path)
            self._state = ConnectionState.CONNECTED
            self._retry_count = 0
            self._last_error = None
        except Exception as e:
            self._state = ConnectionState.DISCONNECTED
            self._last_error = str(e)
            self._schedule_reconnect(account_id, mini_qmt_path)
            raise

    def on_disconnected(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._last_disconnect_at = datetime.utcnow()
        self._last_error = "QMT 连接断开"
        account_id = self._account_service.account_id
        qmt_path = self._account_service.mini_qmt_path
        self._schedule_reconnect(account_id, qmt_path)

    def _schedule_reconnect(self, account_id: str, mini_qmt_path: str) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(account_id, mini_qmt_path)
        )

    async def _reconnect_loop(self, account_id: str, mini_qmt_path: str) -> None:
        while self._retry_count < self._max_retries:
            delay = min(self._base_delay * (2 ** self._retry_count), self._max_delay)
            delay = delay * (0.5 + random.random())  # 抖动
            logger.warning(f"{delay:.1f}秒后尝试重连 QMT...")
            await asyncio.sleep(delay)

            self._state = ConnectionState.RECONNECTING
            try:
                self._account_service.connect(account_id, mini_qmt_path)
                self._state = ConnectionState.CONNECTED
                self._retry_count = 0
                self._last_error = None
                logger.info("QMT 重连成功")
                # 重新订阅回调、恢复订单跟踪
                await self._on_reconnected()
                return
            except Exception as e:
                self._retry_count += 1
                self._last_error = str(e)
                logger.error(f"QMT 重连失败: {e}")

        logger.error("QMT 重连次数超限，进入手动恢复状态")
        self._state = ConnectionState.DISCONNECTED

    async def _on_reconnected(self) -> None:
        # 重新加载 pending 订单、重新订阅行情等
        pass
```

#### 1.2 改造回调

```python
class MyXtQuantTraderCallback:
    def __init__(self, order_tracker=None, connection_manager=None):
        self.order_tracker = order_tracker
        self.connection_manager = connection_manager

    def on_disconnected(self):
        logger.warning("【连接断开】")
        if self.connection_manager:
            self.connection_manager.on_disconnected()
```

#### 1.3 连接健康检查

后台任务定期检测连接状态：

```python
async def _health_check_loop(self):
    while self.running:
        if self.connection_manager.state == ConnectionState.CONNECTED:
            try:
                self.account_service.query_asset()
            except Exception:
                self.connection_manager.on_disconnected()
        await asyncio.sleep(30)
```

### Step 2：订单处理队列（2-3 天）

#### 2.1 队列设计

`backend/reliability/order_queue.py`：

```python
import asyncio
from dataclasses import dataclass
from typing import Callable

@dataclass
class SignalTask:
    id: str
    endpoint: str
    payload: dict
    token: str
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

class OrderQueue:
    def __init__(self, signal_service: ISignalService, alerter, max_retries=3):
        self._queue = asyncio.Queue()
        self._signal_service = signal_service
        self._alerter = alerter
        self._max_retries = max_retries
        self._processor_task = None
        self._processed_count = 0
        self._failed_count = 0

    async def put(self, task: SignalTask) -> None:
        await self._queue.put(task)

    def size(self) -> int:
        return self._queue.qsize()

    async def start(self):
        self._processor_task = asyncio.create_task(self._process_loop())

    async def stop(self):
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self):
        while True:
            task = await self._queue.get()
            try:
                await self._process_one(task)
                self._processed_count += 1
            except Exception as e:
                self._failed_count += 1
                logger.exception(f"处理信号失败: {e}")
                if task.retry_count < self._max_retries:
                    task.retry_count += 1
                    await self._queue.put(task)
                else:
                    self._alerter.alert(f"信号处理失败超过重试次数: {task.id}")
            finally:
                self._queue.task_done()

    async def _process_one(self, task: SignalTask):
        # 幂等性检查：如果 task.id 已处理过，跳过
        # 调用 signal_service.process_signal
        result = await self._signal_service.process_signal(
            task.endpoint, task.payload, task.token
        )
        logger.info(f"信号处理完成: {task.id}")
```

#### 2.2 幂等性保证

每个信号生成唯一 `task.id`（如 signal_log 的 id），处理前检查是否已存在对应订单：

```python
async def _process_one(self, task: SignalTask):
    existing_order = self._order_repo.get_by_signal_task_id(task.id)
    if existing_order:
        logger.info(f"信号 {task.id} 已处理，跳过")
        return
    # ... 处理
```

#### 2.3 改造信号接收端点

```python
@router.post("/jukuan_order")
async def jukuan_order(
    request: dict,
    token: StrategyToken = Depends(verify_strategy_token),
    order_queue: OrderQueue = Depends(get_order_queue)
):
    task = SignalTask(
        id=uuid.uuid4().hex,
        endpoint="jukuan_order",
        payload=request,
        token=token
    )
    await order_queue.put(task)
    return {"success": True, "data": {"task_id": task.id, "message": "信号已入队"}}
```

注意：返回改为"已入队"而非"已下单"，前端需要轮询或 WebSocket 查询处理结果。

### Step 3：审计日志（1-2 天）

#### 3.1 审计器

`backend/reliability/auditor.py`：

```python
class Auditor:
    def __init__(self, audit_repo):
        self._audit_repo = audit_repo

    def log(self, actor_type: str, actor_id: str, action: str,
            resource_type: str = None, resource_id: str = None,
            detail: dict = None, ip: str = None, user_agent: str = None):
        self._audit_repo.create(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
            ip=ip,
            user_agent=user_agent
        )
```

#### 3.2 在关键操作处埋点

- 登录/登出：`auth/login`、`auth/logout`
- 启停服务：`start-server`、`stop-server`
- 创建/更新/删除策略：`POST/PUT/DELETE /api/strategies/*`
- 下单：信号入队时记录 `actor_type=strategy_token, action=place_order`
- 撤单：未来撤单接口
- 修改配置：策略 toggle、Token 吊销

使用 FastAPI 中间件自动记录所有写请求：

```python
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method in ("POST", "PUT", "DELETE"):
        auditor.log(
            actor_type="...",
            actor_id="...",
            action=f"{request.method} {request.url.path}",
            ip=request.client.host,
            user_agent=request.headers.get("user-agent"),
            detail={"status_code": response.status_code}
        )
    return response
```

### Step 4：多渠道告警（1-2 天）

#### 4.1 告警器抽象

`backend/reliability/alerter.py`：

```python
from abc import ABC, abstractmethod

class AlertChannel(ABC):
    @abstractmethod
    async def send(self, title: str, message: str) -> bool: ...

class WeChatChannel(AlertChannel):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, title: str, message: str) -> bool:
        # 复用现有 WeChatHandler 逻辑
        ...

class DingTalkChannel(AlertChannel):
    def __init__(self, webhook_url: str, secret: str = None):
        self.webhook_url = webhook_url
        self.secret = secret

    async def send(self, title: str, message: str) -> bool:
        # 钉钉机器人签名算法
        ...

class FeishuChannel(AlertChannel):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, title: str, message: str) -> bool:
        # 飞书机器人
        ...

class Alerter:
    def __init__(self, channels: List[AlertChannel], min_interval_seconds=60):
        self._channels = channels
        self._min_interval = min_interval_seconds
        self._last_alert_at = {}  # 按 alert_key 去重

    async def alert(self, title: str, message: str, alert_key: str = None):
        if alert_key:
            last = self._last_alert_at.get(alert_key)
            if last and (datetime.utcnow() - last).seconds < self._min_interval:
                return
            self._last_alert_at[alert_key] = datetime.utcnow()

        for channel in self._channels:
            try:
                await channel.send(title, message)
            except Exception as e:
                logger.error(f"告警发送失败: {e}")
```

#### 4.2 配置

`config/settings.py`：

```python
ALERT_CHANNELS: str = os.getenv("ALERT_CHANNELS", "")  # wechat,dingtalk,feishu
WECHAT_WEBHOOK_URL: str = os.getenv("WECHAT_WEBHOOK_URL", "")
DINGTALK_WEBHOOK_URL: str = os.getenv("DINGTALK_WEBHOOK_URL", "")
DINGTALK_SECRET: str = os.getenv("DINGTALK_SECRET", "")
FEISHU_WEBHOOK_URL: str = os.getenv("FEISHU_WEBHOOK_URL", "")
ALERT_MIN_INTERVAL_SECONDS: int = int(os.getenv("ALERT_MIN_INTERVAL_SECONDS", "60"))
```

#### 4.3 告警触发点

- QMT 连接断开/重连失败
- 订单失败（非用户原因，如 QMT 返回错误）
- 信号处理失败超过重试次数
- 策略持仓与账户持仓对账不一致
- 服务异常退出

### Step 5：健康检查端点（0.5-1 天）

`backend/routers/health.py`：

```python
@router.get("/health")
async def health(
    account_service: IAccountService = Depends(get_account_service),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
    order_queue: OrderQueue = Depends(get_order_queue)
):
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "qmt_connected": connection_manager.state == ConnectionState.CONNECTED,
            "qmt_state": connection_manager.state.value,
            "account_id": account_service.account_id,
            "queue_size": order_queue.size(),
            "processed_count": order_queue.processed_count,
            "failed_count": order_queue.failed_count,
            "last_disconnect_at": connection_manager.last_disconnect_at,
            "last_error": connection_manager.last_error,
            "timestamp": datetime.utcnow().isoformat()
        }
    }
```

### Step 6：集成与测试（2-3 天）

#### 6.1 集成

- `QMTServer` 使用 `ConnectionManager` 管理连接。
- `SignalService` 不再直接下单，而是将任务放入 `OrderQueue`。
- 所有关键操作通过 `Auditor` 记录。
- 异常事件通过 `Alerter` 推送。

#### 6.2 测试

- **断连重连测试**：模拟 `on_disconnected`，验证重连次数和退避时间。
- **队列测试**：并发放入 100 个任务，验证全部处理且无重复。
- **幂等测试**：同一任务多次入队，只下一次单。
- **告警测试**：模拟异常，验证告警通道收到消息。
- **健康检查测试**：验证 `/health` 返回结构。

---

## 六、关键决策

### 6.1 为什么用 asyncio.Queue 而不是 Celery？

- 当前项目是单机单进程，asyncio.Queue 足够且无需额外依赖。
- Celery 引入 Redis/RabbitMQ 增加部署复杂度。
- 如果未来需要分布式处理，可平滑迁移到 Celery。

### 6.2 为什么信号返回"已入队"而不是"已下单"？

- 队列化处理后，下单是异步的，无法立即知道结果。
- 前端需要通过订单查询接口或 WebSocket 获取最终结果。
- 这是异步系统的正常语义。

### 6.3 为什么重连要指数退避？

- QMT 断连可能是临时网络波动，也可能是 QMT 客户端崩溃。
- 指数退避避免频繁重连消耗资源。
- 最大延迟 60 秒，避免过长等待。

### 6.4 为什么告警需要按 key 去重？

- QMT 断连后可能每秒触发多次 `on_disconnected`。
- 按 key 去重避免告警风暴。
- 默认 60 秒间隔，关键事件可单独配置更短间隔。

### 6.5 审计日志用中间件还是手动埋点？

- 中间件自动记录所有写请求，保证不遗漏。
- 手动埋点用于记录更详细的业务上下文（如策略变更前后的值）。
- 两者结合使用。

---

## 七、风险与回滚

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 队列处理延迟导致信号响应变慢 | 中 | 队列 consumer 数量可配置；性能测试验证 |
| 自动重连导致订单状态不同步 | 高 | 重连后重新加载 pending 订单；轮询补偿 |
| 告警配置错误导致漏告/滥发 | 中 | 提供测试告警按钮；默认只发 ERROR 级别 |
| 异步返回"已入队"前端未适配 | 高 | 同步更新前端订单监控逻辑；文档说明 |
| 幂等性实现不完善导致重复下单 | 高 | 单元测试覆盖；生产前压测 |

**回滚策略**：

- 通过 feature flag `USE_ORDER_QUEUE` 控制是否使用队列，可切回同步处理。
- 自动重连可配置开关 `AUTO_RECONNECT_ENABLED`。

---

## 八、任务清单

### 连接管理

- [ ] 实现 `backend/reliability/connection_manager.py`
- [ ] 改造 `qmt_client.py` 回调，注入 ConnectionManager
- [ ] 在 `QMTServer` 中使用 ConnectionManager
- [ ] 实现健康检查后台任务
- [ ] 重连后恢复 pending 订单跟踪

### 订单队列

- [ ] 实现 `backend/reliability/order_queue.py`
- [ ] 实现信号任务幂等性检查
- [ ] 改造信号端点改为入队
- [ ] 配置队列 consumer 数量
- [ ] 处理失败重试逻辑

### 审计

- [ ] 实现 `backend/reliability/auditor.py`
- [ ] 创建 `audit_logs` Repository（如 Phase 1 未完成）
- [ ] 实现审计中间件
- [ ] 关键业务操作手动埋点

### 告警

- [ ] 实现 `backend/reliability/alerter.py`
- [ ] 实现 WeChatChannel
- [ ] 实现 DingTalkChannel
- [ ] 实现 FeishuChannel
- [ ] 配置告警渠道和去重间隔
- [ ] 在关键异常点触发告警

### 健康检查

- [ ] 创建 `backend/routers/health.py`
- [ ] 暴露 QMT 状态、队列长度、错误信息

### 测试

- [ ] 断连重连单元测试
- [ ] 订单队列并发测试
- [ ] 幂等性测试
- [ ] 告警渠道 mock 测试
- [ ] 健康检查测试
- [ ] 完整回归测试

### 文档

- [ ] 更新 README（告警配置、队列说明）
- [ ] 更新 IMPLEMENTATION_PLAN

---

## 九、时间安排（预估 8-12 天）

| 阶段 | 时间 | 产出 |
|------|------|------|
| Step 1 连接管理 | 2-3 天 | ConnectionManager、自动重连 |
| Step 2 订单队列 | 2-3 天 | OrderQueue、信号端点改造 |
| Step 3 审计 | 1-2 天 | Auditor、中间件、埋点 |
| Step 4 告警 | 1-2 天 | Alerter、三渠道实现 |
| Step 5 健康检查 | 0.5-1 天 | /health 端点 |
| Step 6 测试 | 2-3 天 | 可靠性测试、回归测试 |
| 文档 | 0.5 天 | README、IMPLEMENTATION_PLAN |

> 注意：Phase 4 依赖 Phase 1（数据库用于审计/幂等）和 Phase 2（服务层拆分使 ConnectionManager/Queue 更容易注入）。建议在 Phase 1/2 完成后开始。
