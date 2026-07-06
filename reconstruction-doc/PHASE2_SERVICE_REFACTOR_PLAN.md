# Phase 2：服务层拆分与依赖注入改造计划

> 本文档依据 `reconstruction-doc/THINKING.md` 制定，目标是将 `backend/server.py` 中剩余的单体逻辑进一步拆分，引入 FastAPI `Depends` 依赖注入，使每个服务职责单一、可独立测试。

---

## 一、目标与范围

### 1.1 核心目标

1. 将 `backend/server.py` 中剩余的路由注册逻辑拆分到独立 router 模块。
2. 引入 FastAPI `Depends` 实现依赖注入，API 路由通过依赖获取服务实例。
3. 定义清晰的服务边界：
   - `AccountService`：账户/QMT 连接管理
   - `StrategyService`：策略 CRUD、持仓跟踪
   - `OrderService`：订单生命周期、订单查询
   - `SignalService`：信号接收、下单协调
   - `MarketDataService`：行情查询封装
4. 保持现有 API 接口签名不变，前端无需改动。
5. 所有服务可通过接口 mock，便于单元测试。

### 1.2 本次不做

- 数据库持久化（Phase 1）
- JWT 认证改造（Phase 3）
- QMT 自动重连（Phase 4）
- 前端改造（Phase 5）

### 1.3 验收标准

- [ ] `backend/server.py` 行数降至 200 行以内。
- [ ] 新增独立 router 模块：`routers/server.py`、`routers/strategy.py`、`routers/order.py`、`routers/signal.py`、`routers/account.py`、`routers/convert.py`、`routers/docs.py`。
- [ ] 所有路由使用 `Depends` 获取服务实例。
- [ ] 服务层有明确接口（Protocol/ABC），可 mock 测试。
- [ ] 现有 171 个 pytest 用例全部通过。
- [ ] 新增服务层单元测试覆盖核心方法。

---

## 二、现状分析

### 2.1 当前 `QMTServer` 职责

`backend/server.py` 中的 `QMTServer` 目前承担：

1. QMT 连接管理（`init_trader`）
2. 订单状态回调注册（`_register_order_state_callback`）
3. 订单跟踪协调（`_track_and_apply_order`）
4. 账户持仓查询（`_query_account_positions`）
5. 路由注册（`setup_routes`）—— 包含 20+ 个端点
6. 动态端点生成（`convert_method_to_endpoint`）
7. 聚宽下单端点协调（`_jukuan_endpoint`）
8. 后台轮询（`_poll_orders_loop`）

### 2.2 已拆分模块

| 模块 | 当前状态 | 说明 |
|------|---------|------|
| `backend/strategy_manager.py` | ✅ 已拆分 | 策略 CRUD、持仓跟踪 |
| `backend/order_tracker.py` | ✅ 已拆分 | 订单状态机 |
| `backend/jukuan_orders.py` | ✅ 已拆分 | 聚宽风格下单 |
| `backend/qmt_client.py` | ✅ 已拆分 | QMT 连接 |
| `backend/server.py` | 🟡 仍过重 | 路由注册和协调逻辑集中 |

### 2.3 问题

- `server.py` 过大，测试困难。
- 路由直接依赖全局 `_current_server`，无法并行运行多个服务实例。
- 服务之间通过全局变量耦合，mock 困难。
- 新增端点需要修改 `server.py`，容易引入冲突。

---

## 三、目标架构

```
backend/
├── main.py                     # FastAPI 应用入口，注册 router
├── dependencies.py             # FastAPI Depends 依赖提供者
├── services/                   # 业务服务层
│   ├── __init__.py
│   ├── interfaces.py           # 服务接口（Protocol）
│   ├── account_service.py      # 账户/QMT 连接服务
│   ├── strategy_service.py     # 策略服务
│   ├── order_service.py        # 订单服务
│   ├── signal_service.py       # 信号/下单协调服务
│   └── market_data_service.py  # 行情服务
├── routers/                    # API 路由层
│   ├── __init__.py
│   ├── server.py               # 服务器启停、状态
│   ├── account.py              # 账户资产、持仓
│   ├── strategy.py             # 策略管理
│   ├── order.py                # 订单监控
│   ├── signal.py               # 聚宽风格信号/下单
│   ├── convert.py              # 代码转换
│   └── docs.py                 # 文档
├── server.py                   # QMTServer 精简版（协调器）
├── strategy_manager.py         # 策略管理器
├── order_tracker.py            # 订单跟踪器
└── jukuan_orders.py            # 聚宽下单处理器
```

---

## 四、设计原则

1. **路由层只负责 HTTP 协议**：校验、序列化、调用服务，不包含业务逻辑。
2. **服务层只负责业务逻辑**：不直接处理 HTTP 请求/响应。
3. **依赖注入**：FastAPI `Depends` 提供服务实例，测试时可替换为 mock。
4. **接口隔离**：服务通过 Protocol/ABC 定义接口，实现可替换。
5. **保持现有 API**：URL 路径、请求体、响应格式不变。

---

## 五、实施步骤

### Step 1：定义服务接口（1 天）

创建 `backend/services/interfaces.py`：

```python
from typing import Protocol, List, Optional, Dict, Any
from backend.strategy_manager import StrategyCreate, StrategyUpdate

class IAccountService(Protocol):
    def connect(self, account_id: str, mini_qmt_path: str) -> None: ...
    def disconnect(self) -> None: ...
    def is_running(self) -> bool: ...
    def test_connection(self) -> Dict[str, Any]: ...
    def query_asset(self) -> Dict[str, Any]: ...
    def query_positions(self) -> List[Dict[str, Any]]: ...

class IStrategyService(Protocol):
    def list_strategies(self) -> List[Dict[str, Any]]: ...
    def create_strategy(self, data: StrategyCreate) -> Dict[str, Any]: ...
    def update_strategy(self, strategy_id: str, data: StrategyUpdate) -> Optional[Dict[str, Any]]: ...
    def delete_strategy(self, strategy_id: str) -> bool: ...
    def toggle_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]: ...
    def refresh_strategies(self) -> List[Dict[str, Any]]: ...

class IOrderService(Protocol):
    def list_orders(self, **filters) -> List[Dict[str, Any]]: ...
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]: ...
    def clear_orders(self) -> None: ...

class ISignalService(Protocol):
    def process_signal(self, endpoint: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]: ...

class IMarketDataService(Protocol):
    def get_stock_name(self, stock_code: str) -> str: ...
    def get_preclose(self, stock_code: str) -> Optional[float]: ...
    def get_latest_price(self, stock_code: str) -> Optional[float]: ...
```

### Step 2：实现服务类（2-3 天）

#### 2.1 `AccountService`

封装 QMT 连接、账户资产、持仓查询。

```python
class AccountService:
    def __init__(self, qmt_client_factory=create_trader):
        self._client_factory = qmt_client_factory
        self._trader = None
        self._account = None
        self._callback = None
        self._mini_qmt_path = None
        self._account_id = None
        self._running = False

    def connect(self, account_id: str, mini_qmt_path: str) -> None:
        self._account_id = account_id
        self._mini_qmt_path = mini_qmt_path
        self._trader, self._account, self._callback = self._client_factory(
            account_id, mini_qmt_path
        )
        self._running = True

    def disconnect(self) -> None:
        self._running = False
        # 停止 trader...

    def is_running(self) -> bool:
        return self._running

    def query_asset(self) -> Dict[str, Any]: ...
    def query_positions(self) -> List[Dict[str, Any]]: ...
```

#### 2.2 `StrategyService`

包装 `StrategyManager`，加入行情富化。

```python
class StrategyService:
    def __init__(self, strategy_manager: StrategyManager,
                 account_service: IAccountService):
        self._strategy_manager = strategy_manager
        self._account_service = account_service

    def list_strategies(self) -> List[Dict[str, Any]]:
        # 从 StrategyManager 获取，account_service 提供 trader/account
        return self._strategy_manager.list_all_enriched(
            self._account_service.trader,
            self._account_service.account
        )
    # ...
```

#### 2.3 `OrderService`

包装 `OrderTracker`。

```python
class OrderService:
    def __init__(self, order_tracker: OrderTracker):
        self._order_tracker = order_tracker

    def list_orders(self, **filters) -> List[Dict[str, Any]]:
        orders = list(self._order_tracker._orders.values())
        # 过滤、序列化...
        return result
```

#### 2.4 `SignalService`

将当前 `QMTServer._jukuan_endpoint` 逻辑迁移至此。

```python
class SignalService:
    def __init__(self, account_service: IAccountService,
                 strategy_service: IStrategyService,
                 order_tracker: OrderTracker):
        self._account_service = account_service
        self._strategy_service = strategy_service
        self._order_tracker = order_tracker
        self._jukuan_handler = None

    def process_signal(self, endpoint: str, payload: Dict[str, Any],
                       token: str) -> Dict[str, Any]:
        # 解析 token、风控检查、下单、记录 signal_log、跟踪订单
        ...
```

#### 2.5 `MarketDataService`

封装 `backend/utils.py` 中的行情函数。

```python
class MarketDataService:
    def get_stock_names(self, codes: set) -> Dict[str, str]: ...
    def get_precloses(self, codes: set) -> Dict[str, float]: ...
    def get_latest_prices(self, codes: list) -> Dict[str, float]: ...
```

### Step 3：创建 FastAPI 依赖提供者（1 天）

`backend/dependencies.py`：

```python
from fastapi import Request

async def get_account_service(request: Request) -> IAccountService:
    return request.app.state.account_service

async def get_strategy_service(request: Request) -> IStrategyService:
    return request.app.state.strategy_service

async def get_order_service(request: Request) -> IOrderService:
    return request.app.state.order_service

async def get_signal_service(request: Request) -> ISignalService:
    return request.app.state.signal_service

async def get_market_data_service(request: Request) -> IMarketDataService:
    return request.app.state.market_data_service
```

在 `main.py` 中初始化服务并挂载到 `app.state`：

```python
@app.on_event("startup")
async def startup():
    app.state.market_data_service = MarketDataService()
    app.state.account_service = AccountService()
    app.state.strategy_service = StrategyService(
        StrategyManager(), app.state.account_service
    )
    app.state.order_service = OrderService(OrderTracker())
    app.state.signal_service = SignalService(
        app.state.account_service,
        app.state.strategy_service,
        app.state.order_service.order_tracker
    )
```

### Step 4：拆分路由（2-3 天）

#### 4.1 `routers/server.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from backend.dependencies import get_account_service
from backend.services.interfaces import IAccountService

router = APIRouter(prefix="/api")

@router.get("/server-info")
async def server_info(account_service: IAccountService = Depends(get_account_service)):
    return {"success": True, "data": {...}}

@router.post("/start-server")
async def start_server(data: dict,
                       account_service: IAccountService = Depends(get_account_service)):
    # 调用 account_service.connect
    ...

@router.post("/stop-server")
async def stop_server(account_service: IAccountService = Depends(get_account_service)):
    account_service.disconnect()
    return {"success": True, "data": {"message": "服务器已停止"}}

@router.get("/test-connection")
async def test_connection(account_service: IAccountService = Depends(get_account_service)):
    return {"success": True, "data": account_service.test_connection()}
```

#### 4.2 `routers/strategy.py`

```python
@router.get("/strategies")
async def list_strategies(strategy_service: IStrategyService = Depends(get_strategy_service)):
    return {"success": True, "data": strategy_service.list_strategies()}

@router.post("/strategies")
async def create_strategy(data: StrategyCreate,
                          strategy_service: IStrategyService = Depends(get_strategy_service)):
    return {"success": True, "data": strategy_service.create_strategy(data)}

@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, data: StrategyUpdate,
                          strategy_service: IStrategyService = Depends(get_strategy_service)):
    ...

@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str,
                          strategy_service: IStrategyService = Depends(get_strategy_service)):
    ...

@router.post("/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str,
                          strategy_service: IStrategyService = Depends(get_strategy_service)):
    ...

@router.post("/strategies/refresh")
async def refresh_strategies(strategy_service: IStrategyService = Depends(get_strategy_service)):
    ...
```

#### 4.3 `routers/order.py`

```python
@router.get("/orders")
async def get_orders(status: Optional[str] = None,
                     strategy_name: Optional[str] = None,
                     start_date: Optional[str] = None,
                     end_date: Optional[str] = None,
                     order_service: IOrderService = Depends(get_order_service)):
    return {"success": True, "data": order_service.list_orders(
        status=status, strategy_name=strategy_name,
        start_date=start_date, end_date=end_date
    )}
```

#### 4.4 `routers/signal.py`

```python
@router.post("/jukuan_order")
async def jukuan_order(request: dict, x_token: str = Header(...),
                       signal_service: ISignalService = Depends(get_signal_service)):
    return signal_service.process_signal("jukuan_order", request, x_token)

# 同理 jukuan_order_target / jukuan_order_value / jukuan_order_target_value
```

#### 4.5 `routers/account.py`

```python
@router.get("/account-asset")
async def account_asset(account_service: IAccountService = Depends(get_account_service)):
    return {"success": True, "data": account_service.query_asset()}

@router.get("/account-positions")
async def account_positions(account_service: IAccountService = Depends(get_account_service)):
    return {"success": True, "data": account_service.query_positions()}
```

#### 4.6 `routers/convert.py` 和 `routers/docs.py`

将代码转换和文档接口迁移至此。

### Step 5：精简 `QMTServer`（1-2 天）

`QMTServer` 变为轻量协调器：

```python
class QMTServer:
    def __init__(self, account_id: str, mini_qmt_path: str,
                 host: str = "0.0.0.0", port: int = 8000, token: str = None):
        self.account_id = account_id
        self.mini_qmt_path = mini_qmt_path
        self.host = host
        self.port = port
        self.token = token or self.generate_token()
        self.app = FastAPI(title="QMT Live Assistant")
        self.running = False

    def init_and_setup(self, target_app=None):
        # 初始化服务并挂载到 target_app.state
        ...

    def stop(self):
        self.running = False
```

最终 `server.py` 只保留：

- Token 生成
- 服务生命周期协调
- 动态 trader 方法端点生成（可选保留或迁移到 `routers/dynamic.py`）

### Step 6：测试（2-3 天）

#### 6.1 服务层单元测试

使用 mock 实现服务接口：

```python
class MockAccountService:
    def __init__(self):
        self.running = False
    def connect(self, account_id, mini_qmt_path): self.running = True
    def is_running(self): return self.running
    def query_asset(self): return {"cash": 100000}

def test_server_info():
    app.state.account_service = MockAccountService()
    client = TestClient(app)
    response = client.get("/api/server-info")
    assert response.status_code == 200
```

#### 6.2 路由层测试

为每个 router 编写测试，验证 HTTP 契约。

#### 6.3 回归测试

确保原有 171 个测试用例通过。

---

## 六、关键决策

### 6.1 为什么使用 Protocol 而不是 ABC？

- Protocol 是结构性子类型，mock 对象不需要显式继承，写测试更灵活。
- 与类型检查工具（mypy）配合良好。

### 6.2 为什么把服务挂载到 `app.state`？

- FastAPI 推荐的方式，与 `Depends` 配合自然。
- 避免全局变量，支持多应用实例。

### 6.3 为什么保留 `QMTServer`？

- 当前 CLI 入口和桌面壳都依赖 `QMTServer` 类。
- 保留其作为服务生命周期协调器，逐步迁移职责。

### 6.4 动态 trader 方法端点如何处理？

当前 `convert_method_to_endpoint` 动态反射 trader 方法生成端点。建议：

- 保留在 `server.py` 或迁移到 `services/dynamic_endpoint_service.py`。
- 因为该功能使用较少，可暂不拆分，避免过度设计。

---

## 七、风险与回滚

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 路由拆分引入 API 路径变化 | 高 | 保持 URL 路径、请求体、响应格式完全一致；Postman/测试验证 |
| 依赖注入导致测试需要大量 setup | 中 | 提供测试 fixtures 自动初始化 mock 服务 |
| 服务循环依赖 | 中 | 明确依赖方向：SignalService -> AccountService/StrategyService/OrderService |
| 性能下降 | 低 | Depends 开销极小；服务实例在 startup 创建，非每次请求新建 |

**回滚策略**：

- 每次小步提交，发现问题可快速回退到上一版本。
- 保留 `server.py` 旧版本作为备份，必要时恢复。

---

## 八、任务清单

### 接口定义

- [ ] 创建 `backend/services/interfaces.py`
- [ ] 定义 `IAccountService`、`IStrategyService`、`IOrderService`、`ISignalService`、`IMarketDataService`

### 服务实现

- [ ] 实现 `backend/services/account_service.py`
- [ ] 实现 `backend/services/strategy_service.py`
- [ ] 实现 `backend/services/order_service.py`
- [ ] 实现 `backend/services/signal_service.py`
- [ ] 实现 `backend/services/market_data_service.py`

### 依赖注入

- [ ] 创建 `backend/dependencies.py`
- [ ] 在 `main.py` 中初始化服务并挂载到 `app.state`
- [ ] 更新 `QMTServer` 使用服务层

### 路由拆分

- [ ] 创建 `backend/routers/__init__.py`
- [ ] 拆分 `routers/server.py`
- [ ] 拆分 `routers/account.py`
- [ ] 拆分 `routers/strategy.py`
- [ ] 拆分 `routers/order.py`
- [ ] 拆分 `routers/signal.py`
- [ ] 拆分 `routers/convert.py`
- [ ] 拆分 `routers/docs.py`
- [ ] 在 `main.py` 中注册所有 router

### 精简 QMTServer

- [ ] 移除 `server.py` 中已迁移的路由
- [ ] 保留 Token 生成和服务生命周期
- [ ] 将动态 trader 端点保留或迁移

### 测试

- [ ] 新增 `tests/services/` 目录
- [ ] 为每个服务编写单元测试
- [ ] 新增 `tests/routers/` 目录
- [ ] 为关键路由编写 HTTP 测试
- [ ] 运行完整回归测试（171 个用例）

### 文档

- [ ] 更新 `product-doc/IMPLEMENTATION_PLAN.md`
- [ ] 更新 README 中架构说明（可选）

---

## 九、时间安排（预估 7-10 天）

| 阶段 | 时间 | 产出 |
|------|------|------|
| Step 1 接口定义 | 1 天 | `services/interfaces.py` |
| Step 2 服务实现 | 2-3 天 | 5 个服务类 |
| Step 3 依赖注入 | 1 天 | `dependencies.py`、`app.state` 初始化 |
| Step 4 路由拆分 | 2-3 天 | 7 个 router 模块 |
| Step 5 精简 QMTServer | 1-2 天 | `server.py` 降至 200 行以内 |
| Step 6 测试 | 2-3 天 | 服务层/路由层测试、回归测试 |
| Step 7 文档 | 0.5 天 | IMPLEMENTATION_PLAN 更新 |

> 注意：Phase 2 可与 Phase 1 穿插进行。Phase 1 完成 Repository 层后，Phase 2 的服务层可直接依赖 Repository 接口，而非直接依赖内存模型。
