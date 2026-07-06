# Phase 1：数据持久化改造计划

> 本文档依据 `reconstruction-doc/THINKING.md` 中的数据库模型设计，制定第一阶段（数据持久化）的具体实施方案。
> 目标：在不破坏现有功能的前提下，把核心数据（策略、持仓、订单、信号）从内存迁移到数据库，使服务重启后数据不丢失。

---

## 一、目标与范围

### 1.1 核心目标

1. 策略（`strategies`）、策略 Token（`strategy_tokens`）、策略持仓（`positions`）重启不丢失。
2. 订单（`orders`）、订单事件（`order_events`）、信号日志（`signal_logs`）重启不丢失。
3. 保留内存模式作为测试 fallback，通过配置开关切换。
4. 引入 Alembic 管理数据库迁移，便于后续升级。
5. 为后续 Phase 2/3/4（风控、绩效、自动重连）打好数据基础。

### 1.2 本次不做（后续迭代）

- `account_positions`（账户原始持仓缓存）
- `account_snapshots` / `strategy_snapshots`（绩效快照）
- `risk_rules` / `risk_events`（风控）
- `account_status_events`（账号状态事件）
- `order_fills`（成交明细，因当前 `OrderTracker` 只记录汇总成交）
- JWT 认证改造（属于 Phase 3）
- 前端 React 化（属于 Phase 5）

### 1.3 验收标准

- [ ] 新增策略、停止服务、重启服务后，策略列表与持仓一致。
- [ ] 下单后停止服务、重启服务后，订单状态与历史可查询。
- [ ] 现有 171 个 pytest 用例全部通过（含内存模式测试）。
- [ ] 新增 Repository 层单元测试覆盖核心 CRUD。
- [ ] 提供 Alembic 初始迁移脚本，新环境可一键建表。
- [ ] README 更新运行与配置说明。

---

## 二、现状分析

### 2.1 当前内存存储现状

| 当前内存结构 | 所在文件 | 持久化优先级 |
|-------------|---------|-------------|
| `StrategyManager._strategies: Dict[str, Strategy]` | `backend/strategy_manager.py` | 高 |
| `Strategy.positions: list` | `backend/strategy_manager.py` | 高 |
| `Strategy.trading_records: list` | `backend/strategy_manager.py` | 中（合并到 orders） |
| `OrderTracker._orders: Dict[str, TrackedOrder]` | `backend/order_tracker.py` | 高 |
| `QMTServer._jukuan_handler` | `backend/server.py` | 无状态，不持久化 |

### 2.2 需要适配的调用点

1. `StrategyManager.create/update/delete/toggle` → 写入 `strategies` + `positions`
2. `StrategyManager.apply_optimistic_position / rollback / reconcile` → 更新 `positions`
3. `StrategyManager.add_trading_record` → 改为写入 `orders`（或保留 memory 缓存 + 异步写库）
4. `OrderTracker.track_order / update_from_* / _resolve` → 写入 `orders` + `order_events`
5. `QMTServer._track_and_apply_order` → 下单成功后持久化 `orders`
6. 信号接收端点 → 写入 `signal_logs`
7. 服务启动时 → 从数据库加载策略和未完成的 pending 订单

---

## 三、设计原则

1. **最小侵入**：尽量保持 `StrategyManager` 和 `OrderTracker` 的对外接口不变，内部通过 Repository 切换存储后端。
2. **Repository 模式**：业务逻辑依赖抽象 Repository 接口，具体实现可以是 `SQLAlchemyRepository` 或 `InMemoryRepository`。
3. **配置驱动**：通过环境变量 `PERSISTENCE_MODE=sqlite|memory|postgres` 切换存储模式，默认 `sqlite`。
4. **懒加载 + 实时写**：启动时加载策略和 pending 订单；运行时每次状态变更立即写库（SQLite 在本地，延迟可接受）。
5. **Alembic 管理表结构**：所有表变更通过迁移脚本完成，不手动改库。
6. **类型安全**：使用 SQLAlchemy 2.0 声明式模型 + Pydantic v2 做业务层校验。

---

## 四、实施步骤

### Step 1：基础设施搭建（1-2 天）

#### 1.1 添加依赖

更新 `requirements.txt`：

```text
sqlalchemy>=2.0.0
alembic>=1.12.0
psycopg2-binary>=2.9.9  # 生产 PostgreSQL 可选
```

#### 1.2 目录结构

```
backend/
├── db/
│   ├── __init__.py
│   ├── base.py              # SQLAlchemy Base + 引擎/会话工厂
│   ├── session.py           # get_db / 依赖注入
│   ├── models/              # 数据库模型
│   │   ├── __init__.py
│   │   ├── account.py
│   │   ├── strategy.py
│   │   ├── strategy_token.py
│   │   ├── position.py
│   │   ├── order.py
│   │   ├── order_event.py
│   │   └── signal_log.py
│   ├── repositories/        # Repository 实现
│   │   ├── __init__.py
│   │   ├── base.py          # 抽象接口
│   │   ├── sqlalchemy/      # SQLAlchemy 实现
│   │   └── memory/          # 内存实现（测试 fallback）
│   └── migrations/          # Alembic 目录
│       ├── env.py
│       ├── alembic.ini
│       └── versions/
```

#### 1.3 数据库配置

`config/settings.py` 增加：

```python
PERSISTENCE_MODE: str = os.getenv("PERSISTENCE_MODE", "sqlite")
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/qmt_live_assistant.db"
)
```

创建 `data/` 目录并在 `.gitignore` 中忽略 `*.db`。

#### 1.4 引擎与会话

`backend/db/base.py`：

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

_engine = create_engine(settings.DATABASE_URL, echo=settings.DEBUG)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
```

#### 1.5 Alembic 初始化

```bash
alembic init backend/db/migrations
```

配置 `alembic.ini` 指向 `backend/db/base.py` 中的 `Base` 元数据。

---

### Step 2：数据库模型定义（2-3 天）

按 `reconstruction-doc/THINKING.md` 的表结构，首批实现以下模型：

#### 2.1 `accounts`

```python
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    account_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_type: Mapped[str] = mapped_column(String(32), default="STOCK")
    qmt_path: Mapped[str] = mapped_column(String(512))
    broker: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
```

#### 2.2 `strategies`

```python
class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allocated_funds: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    available_cash: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
```

#### 2.3 `strategy_tokens`

```python
class StrategyToken(Base):
    __tablename__ = "strategy_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    token_prefix: Mapped[Optional[str]] = mapped_column(String(16))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

#### 2.4 `positions`

```python
class Position(Base):
    __tablename__ = "positions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"), index=True)
    stock_code: Mapped[str] = mapped_column(String(16))
    stock_name: Mapped[Optional[str]] = mapped_column(String(64))
    direction: Mapped[Optional[str]] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, default=0)
    frozen_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("strategy_id", "stock_code", coalesce("direction", "")),
    )
```

#### 2.5 `orders`

```python
class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("strategies.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    external_order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    order_sysid: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    stock_code: Mapped[str] = mapped_column(String(16))
    source_code: Mapped[Optional[str]] = mapped_column(String(24))
    source_platform: Mapped[Optional[str]] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    offset_flag: Mapped[Optional[str]] = mapped_column(String(16))
    order_type: Mapped[int] = mapped_column(Integer)
    price_type: Mapped[Optional[int]] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    filled_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    status_msg: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(String(32))
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exchange_order_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    strategy_name: Mapped[Optional[str]] = mapped_column(String(128))
    order_remark: Mapped[Optional[str]] = mapped_column(String(64))
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    response_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
```

> 注：如果当前使用 SQLite（无 JSONB），可用 `JSON` 类型。

#### 2.6 `order_events`

```python
class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[Optional[str]] = mapped_column(String(16))
    to_status: Mapped[Optional[str]] = mapped_column(String(16))
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

#### 2.7 `signal_logs`

```python
class SignalLog(Base):
    __tablename__ = "signal_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[Optional[str]] = mapped_column(ForeignKey("strategies.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    source_platform: Mapped[Optional[str]] = mapped_column(String(32))
    source_ip: Mapped[Optional[str]] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    processed_order_id: Mapped[Optional[str]] = mapped_column(ForeignKey("orders.id"), index=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

#### 2.8 生成 Alembic 初始迁移

```bash
alembic revision --autogenerate -m "init core tables"
alembic upgrade head
```

---

### Step 3：Repository 层实现（2-3 天）

#### 3.1 抽象接口

`backend/db/repositories/base.py`：

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional

T = TypeVar("T")

class Repository(ABC, Generic[T]):
    @abstractmethod
    def add(self, entity: T) -> T: ...
    @abstractmethod
    def get(self, id: str) -> Optional[T]: ...
    @abstractmethod
    def update(self, entity: T) -> T: ...
    @abstractmethod
    def delete(self, id: str) -> bool: ...
    @abstractmethod
    def list_all(self, **filters) -> List[T]: ...
```

#### 3.2 SQLAlchemy 通用实现

```python
class SQLAlchemyRepository(Repository[T], Generic[T]):
    def __init__(self, session: Session, model_class: type):
        self._session = session
        self._model_class = model_class

    def add(self, entity: T) -> T:
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get(self, id: str) -> Optional[T]:
        return self._session.get(self._model_class, id)

    def update(self, entity: T) -> T:
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def delete(self, id: str) -> bool:
        obj = self.get(id)
        if obj:
            self._session.delete(obj)
            self._session.commit()
            return True
        return False

    def list_all(self, **filters) -> List[T]:
        query = self._session.query(self._model_class)
        for key, value in filters.items():
            if hasattr(self._model_class, key) and value is not None:
                query = query.filter(getattr(self._model_class, key) == value)
        return query.all()
```

#### 3.3 针对业务的 Repository

- `StrategyRepository`：包含策略 + Token + 持仓的级联加载
- `OrderRepository`：包含订单事件写入
- `SignalLogRepository`
- `AccountRepository`

#### 3.4 内存实现（测试 fallback）

```python
class InMemoryRepository(Repository[T], Generic[T]):
    def __init__(self):
        self._store: Dict[str, T] = {}

    def add(self, entity: T) -> T:
        self._store[entity.id] = entity
        return entity
    # ... 其他方法
```

#### 3.5 Repository 工厂

```python
def get_repository(session: Session, model_class: type, mode: str = None) -> Repository:
    mode = mode or settings.PERSISTENCE_MODE
    if mode == "memory":
        return InMemoryRepository(model_class)
    return SQLAlchemyRepository(session, model_class)
```

---

### Step 4：服务层改造（3-5 天）

#### 4.1 `StrategyManager` 改造

**当前问题**：`Strategy` 是 Pydantic 模型，内部直接操作 `self._strategies: Dict[str, Strategy]`。

**改造方案**：

1. 新增 `StrategyEntity`（或复用 Pydantic `Strategy` 作为 DTO），数据库模型为 `StrategyModel`。
2. `StrategyManager` 构造函数接收 `strategy_repo: StrategyRepository`。
3. `create` / `update` / `delete` / `toggle` 中调用 Repository。
4. `update_position` / `apply_optimistic_position` / `reconcile_position` 同步更新数据库中的 `positions`。
5. `list_all_enriched` 从 Repository 加载策略，再用 QMT 行情富化。

**伪代码**：

```python
class StrategyManager:
    def __init__(self, strategy_repo: Optional[StrategyRepository] = None):
        self._repo = strategy_repo or InMemoryStrategyRepository()

    def create(self, data: StrategyCreate) -> Strategy:
        # 业务校验...
        entity = Strategy(...)
        self._repo.save(entity)  # 级联保存 positions
        return entity

    def update_position(self, strategy_id, stock_code, direction, quantity, price):
        entity = self._repo.get(strategy_id)
        # 内存更新...
        self._repo.save(entity)
```

#### 4.2 `OrderTracker` 改造

**改造方案**：

1. `OrderTracker` 构造函数接收 `order_repo: OrderRepository`。
2. `track_order` 时：先创建内存 `TrackedOrder`，再异步/同步写入数据库 `orders` + `order_events('placed')`。
3. `update_from_callback` / `update_from_trade` / `update_from_error` 更新内存状态，并写入 `order_events`。
4. `_resolve` 到达终态时，更新 `orders.status` 并写入 `order_events`。
5. 启动时从数据库加载 `status IN ('pending', 'partial')` 的订单到内存。

#### 4.3 `QMTServer` 改造

1. 构造 `QMTServer` 时创建数据库会话和 Repository 实例。
2. 把 Repository 注入 `StrategyManager` 和 `OrderTracker`。
3. 信号端点（`jukuan_order*`）中记录 `signal_logs`。
4. 启动时：
   - 如果数据库中已有 account 记录，尝试自动连接 QMT（可选）。
   - 加载策略列表。
   - 加载 pending/partial 订单到 `OrderTracker`。

#### 4.4 保持内存模式兼容

通过 `PERSISTENCE_MODE=memory` 启用纯内存实现，确保现有测试无需数据库即可运行。

---

### Step 5：启动/停止/实时持久化（1-2 天）

#### 5.1 启动加载

`QMTServer.init_and_setup` 中增加：

```python
async def init_and_setup(self, target_app=None):
    # 1. 初始化数据库会话
    self._db = SessionLocal()
    # 2. 创建 Repository
    strategy_repo = StrategyRepository(self._db)
    order_repo = OrderRepository(self._db)
    # 3. 注入到 Manager
    self.strategy_manager = StrategyManager(strategy_repo)
    self.order_tracker = OrderTracker(order_repo)
    # 4. 加载 pending 订单
    pending_orders = order_repo.list_pending()
    for order in pending_orders:
        self.order_tracker.load_from_db(order)
    # 5. 初始化 QMT 连接
    self.init_trader()
    self.setup_routes(target_app=target_app)
    self.running = True
    self._poll_task = asyncio.create_task(self._poll_orders_loop())
```

#### 5.2 实时持久化 vs 快照持久化

**选择：实时持久化**。原因：

- SQLite 本地写入延迟通常在毫秒级，不影响下单链路。
- 服务异常退出时数据不会丢失。
- 实现简单，不需要复杂的快照/事务合并逻辑。

**优化**：如果未来 SQLite 成为瓶颈，可改为批量写入或 WAL 模式。

#### 5.3 会话生命周期

- 每个 HTTP 请求使用独立会话（FastAPI Depends）。
- `StrategyManager` / `OrderTracker` 持有长会话，每次操作后 `commit()`。
- 服务停止时关闭会话。

---

### Step 6：测试（2-3 天）

#### 6.1 Repository 单元测试

为每个 Repository 编写测试，使用 SQLite 内存数据库（`:memory:`）：

```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

覆盖：

- Strategy CRUD + 级联持仓
- StrategyToken 吊销/过期查询
- Order 创建 + 状态更新 + 事件记录
- SignalLog 创建 + 按策略查询

#### 6.2 服务层集成测试

- `StrategyManager` 使用 SQLAlchemy StrategyRepository 创建策略并更新持仓。
- `OrderTracker` 使用 SQLAlchemy OrderRepository 跟踪订单生命周期。
- 重启场景测试：停止服务、重新创建、验证数据恢复。

#### 6.3 现有测试兼容

- 默认测试配置 `PERSISTENCE_MODE=memory`。
- 原有 `test_strategy_manager.py` / `test_order_tracker.py` 仍使用内存模式。
- 新增 `test_repositories.py` 专门测试数据库模式。

#### 6.4 覆盖率目标

- Repository 层：80%+
- 服务层数据库集成：新增关键路径覆盖

---

### Step 7：文档与迁移（1 天）

#### 7.1 README 更新

- 新增依赖安装说明（SQLAlchemy + Alembic）。
- 新增 `PERSISTENCE_MODE` 环境变量说明。
- 新增数据库迁移命令：
  ```bash
  alembic upgrade head
  ```

#### 7.2 IMPLEMENTATION_PLAN 更新

- 标记 Phase 1 为进行中/已完成。
- 更新架构图，加入 Database + Repository 层。

#### 7.3 Alembic 迁移脚本

- 提交 `backend/db/migrations/versions/xxxx_init_core_tables.py`。
- 提供回滚命令：
  ```bash
  alembic downgrade -1
  ```

---

## 五、关键决策

### 5.1 为什么使用 SQLAlchemy 2.0 声明式模型？

- 类型注解支持更好，与 Pydantic v2 配合更顺畅。
- 是当前 Python ORM 的事实标准，文档和社区资源丰富。

### 5.2 为什么保留内存模式？

- 现有 171 个测试用例运行在 macOS/Linux，依赖 `mock_xtquant`。
- 如果测试全部改为 SQLite，会增加测试启动时间和复杂度。
- 内存模式保证核心逻辑测试快速、无外部依赖。

### 5.3 为什么先不做 `order_fills`？

- 当前 `OrderTracker` 只记录 `filled_quantity` 和 `filled_price` 汇总。
- 引入 `order_fills` 需要改动 `update_from_trade` 和 `_accumulate_fill` 逻辑。
- 可在 Phase 1 完成后的小迭代中补充，不影响核心目标。

### 5.4 为什么 `positions` 和 `orders` 要实时写库？

- 实盘场景下，服务崩溃或升级重启不应丢失未完成的订单和持仓。
- SQLite WAL 模式下写入开销低，不会成为瓶颈。

### 5.5 为什么 `accounts` 也要持久化？

- 服务重启后需要知道连接哪个 QMT 实例。
- 为后续多账户管理打基础。
- 当前启动时从配置文件或前端传入的 account_id/qmt_path 可写入 accounts 表。

---

## 六、风险与回滚

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 数据库写入延迟影响下单 | 中 | SQLite WAL 模式；Repository 操作在后台不阻塞 QMT 下单；性能测试验证 |
| SQLAlchemy 模型与 Pydantic 模型转换复杂 | 中 | 定义清晰的 Entity/DTO/Model 分层；使用工具函数转换 |
| 现有测试大量失败 | 高 | 保留内存模式；新增测试与旧测试隔离；逐步迁移 |
| Alembic 迁移失败 | 低 | 开发环境反复测试；提供 `alembic downgrade` 回滚 |
| 数据模型后续变更导致迁移冲突 | 中 | Phase 1 表结构尽量稳定；后续变更通过 Alembic 增量迁移 |
| SQLite 并发写入锁 | 中 | 单机单进程使用，GIL 保证同一时刻只有一个写；后续切 PostgreSQL |

**回滚策略**：

- 如果发现严重问题，设置 `PERSISTENCE_MODE=memory` 即可恢复到改造前行为。
- 数据库文件可删除后重建（开发环境）。
- 生产环境需提供数据库备份脚本。

---

## 七、任务清单

### 基础设施

- [ ] 更新 `requirements.txt`（SQLAlchemy, Alembic, psycopg2-binary）
- [ ] 创建 `backend/db/` 目录结构
- [ ] 实现 `backend/db/base.py`（Base, engine, SessionLocal）
- [ ] 配置 `config/settings.py`（PERSISTENCE_MODE, DATABASE_URL）
- [ ] 初始化 Alembic
- [ ] 创建 `data/` 目录并更新 `.gitignore`

### 模型

- [ ] `Account` 模型
- [ ] `Strategy` 模型
- [ ] `StrategyToken` 模型
- [ ] `Position` 模型
- [ ] `Order` 模型
- [ ] `OrderEvent` 模型
- [ ] `SignalLog` 模型
- [ ] 生成 Alembic 初始迁移脚本

### Repository

- [ ] 抽象 `Repository` 接口
- [ ] `SQLAlchemyRepository` 通用实现
- [ ] `InMemoryRepository` 通用实现
- [ ] `StrategyRepository`（含级联持仓/Token）
- [ ] `OrderRepository`（含事件写入）
- [ ] `SignalLogRepository`
- [ ] `AccountRepository`
- [ ] Repository 工厂

### 服务层适配

- [ ] 改造 `StrategyManager` 使用 Repository
- [ ] 改造 `OrderTracker` 使用 Repository
- [ ] 改造 `QMTServer` 注入 Repository 和加载逻辑
- [ ] 信号端点写入 `signal_logs`
- [ ] 启动时加载策略和 pending 订单

### 测试

- [ ] 新增 `tests/repositories/` 测试目录
- [ ] StrategyRepository 单元测试
- [ ] OrderRepository 单元测试
- [ ] SignalLogRepository 单元测试
- [ ] StrategyManager + Repository 集成测试
- [ ] OrderTracker + Repository 集成测试
- [ ] 重启恢复测试
- [ ] 确保内存模式下原有 171 个测试通过

### 文档

- [ ] 更新 README.md（依赖、环境变量、迁移命令）
- [ ] 更新 `product-doc/IMPLEMENTATION_PLAN.md`
- [ ] 提交 Alembic 迁移脚本

---

## 八、时间安排（预估 10-14 天）

| 阶段 | 时间 | 产出 |
|------|------|------|
| Step 1 基础设施 | 1-2 天 | 依赖、目录、Alembic、配置 |
| Step 2 模型定义 | 2-3 天 | 7 个模型、初始迁移脚本 |
| Step 3 Repository | 2-3 天 | 抽象接口、SQLAlchemy/内存实现 |
| Step 4 服务层改造 | 3-5 天 | StrategyManager/OrderTracker/QMTServer 适配 |
| Step 5 启动/停止 | 1-2 天 | 加载逻辑、实时持久化 |
| Step 6 测试 | 2-3 天 | Repository 测试、集成测试、回归测试 |
| Step 7 文档 | 1 天 | README、IMPLEMENTATION_PLAN、迁移脚本 |

> 实际执行时建议采用小步提交：每完成一个 Repository 或服务类改造就提交一次，便于 review 和回滚。
