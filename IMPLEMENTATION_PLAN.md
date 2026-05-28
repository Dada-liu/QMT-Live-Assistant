# QMT-live-assistant 实现方案

## Context

根据 PR.md 需求，构建一个基于 Python 服务器 + 原生 HTML 前端的 miniQMT 量化交易助手。Python 服务器代码参考 `../qka` 项目，UI 设计采用 DESIGN.md 中定义的 Coinbase 风格。项目 MVP 包括：启动 miniQMT 连接、测试获取可用资金、聚宽代码转换、信号监控。

## 技术栈

- **后端**: Python 3.10+ / FastAPI / uvicorn / xtquant SDK
- **前端**: 原生 HTML + CSS + JS（无框架，ES Module）
- **设计**: Coinbase 设计系统（#0052ff 主色，Inter 字体，pill 按钮，24px 卡片圆角）

## 项目架构图示

### 1. 整体系统架构

```mermaid
graph TB
    subgraph 远程层["☁️ 远程信号服务器"]
        DS[策略引擎]
    end

    subgraph 本地层["🖥️ 本地 Python 服务器"]
        subgraph 入口层["入口层"]
            MAIN[main.py<br/>FastAPI 应用]
        end
        subgraph 核心层["核心层"]
            SVR[server.py<br/>QMTServer<br/>动态端点生成]
            SIG[signal_handler.py<br/>SignalReceiver<br/>远程信号接收]
            CLIENT[qmt_client.py<br/>QMT 连接 + 代码转换]
        end
        subgraph 基础设施层["基础设施层"]
            LOG[logger.py<br/>日志系统]
            UTILS[utils.py<br/>工具函数]
            CONST[constants.py<br/>常量定义]
            CFG[config/settings.py<br/>配置管理]
        end
    end

    subgraph QMT层["📊 miniQMT 交易终端"]
        XT[XtQuantTrader<br/>讯投 SDK]
    end

    subgraph 前端层["🌐 浏览器 GUI"]
        subgraph HTML["index.html"]
            CFG_PANEL[配置面板]
            SVR_INFO[服务器信息]
            SIG_MON[信号监控]
            JQ_CONV[聚宽转换]
            DASH[账户仪表板]
        end
        subgraph JS["JS Modules"]
            STATE[state.js]
            API[api.js]
            UI[ui.js]
            CONFIG_JS[config-panel.js]
            MON_JS[monitor.js]
            DASH_JS[dashboard.js]
        end
    end

    DS -->|"POST /api/receive-signal<br/>(JSON 信号)"| MAIN
    MAIN --> SVR
    MAIN --> SIG
    SVR --> CLIENT
    CLIENT -->|"XtQuant SDK"| XT
    SIG --> CLIENT
    CLIENT --> UTILS
    CLIENT --> LOG
    SVR --> LOG
    MAIN --> CFG
    CLIENT --> CONST
    SIG --> CONST

    SVR <-->|"信号日志"| SIG
    MAIN <-->|"HTTP API"| API
    API --> HTML
    STATE --> JS
```

### 2. 项目目录结构

```mermaid
graph LR
    subgraph ROOT["QMT-live-assistant/"]
        direction TB
        BE["backend/<br/>Python 后端"]
        FE["frontend/<br/>原生 HTML/JS/CSS"]
        CFG_DIR["config/<br/>配置"]
        TEST["tests/<br/>测试"]
        REQ["requirements.txt"]
        README["README.md"]
    end

    subgraph "backend/ 内部"
        MAIN2["main.py"]
        SVR2["server.py"]
        CLIENT2["qmt_client.py"]
        SIG2["signal_handler.py"]
        UTILS2["utils.py"]
        LOG2["logger.py"]
        CONST2["constants.py"]
        MOCK["mock_xtquant/"]
    end

    subgraph "frontend/ 内部"
        HTML2["index.html"]
        CSS["styles.css"]
        JS_DIR["js/"]
    end

    subgraph "frontend/js/ 内部"
        APP_JS["app.js (入口)"]
        STATE_JS["state.js"]
        API_JS["api.js"]
        UI_JS["ui.js"]
        CFG_JS["config-panel.js"]
        MON_JS2["monitor.js"]
        DASH_JS2["dashboard.js"]
    end

    BE --> MAIN2 & SVR2 & CLIENT2 & SIG2 & UTILS2 & LOG2 & CONST2 & MOCK
    FE --> HTML2 & CSS & JS_DIR
    JS_DIR --> APP_JS & STATE_JS & API_JS & UI_JS & CFG_JS & MON_JS2 & DASH_JS2
```

### 3. 核心数据流

```mermaid
sequenceDiagram
    actor 用户 as 👤 用户浏览器
    participant Frontend as 🌐 前端 GUI
    participant Main as main.py
    participant Svr as server.py<br/>QMTServer
    participant Sig as signal_handler.py<br/>SignalReceiver
    participant Client as qmt_client.py
    participant QMT as 📊 miniQMT

    Note over 用户,QMT: === 启动流程 ===
    用户->>Frontend: 填写配置表单（账号ID、QMT路径）
    Frontend->>Main: POST /api/start-server
    Main->>Svr: 创建 QMTServer 实例（后台线程）
    Svr->>Client: create_trader(account_id, path)
    Client->>QMT: XtQuantTrader.start() + connect()
    QMT-->>Client: 连接成功
    Client->>QMT: subscribe(account)
    Client->>QMT: register_callback(callback)
    Svr->>Svr: setup_routes() 动态注册所有 API 端点
    Main-->>Frontend: 返回 {token, server_info}

    Note over 用户,QMT: === 连接测试流程 ===
    用户->>Frontend: 点击「测试连接」
    Frontend->>Svr: GET /api/test-connection (X-Token)
    Svr->>Client: trader.query_stock_asset(account)
    Client->>QMT: 查询资产
    QMT-->>Client: 返回资产数据
    Client-->>Svr: XtAsset 对象
    Svr->>Svr: convert_to_dict()
    Svr-->>Frontend: {可用资金, 持仓市值, 总资产, 当日盈亏}
    Frontend->>Frontend: 更新仪表板

    Note over 用户,QMT: === 远程信号流程 ===
    actor Remote as ☁️ 远程策略服务器
    Remote->>Main: POST /api/receive-signal<br/>{signal_id, stock_code, direction, quantity}
    Main->>Sig: SignalReceiver.receive_signal(signal)
    Sig->>Sig: 校验信号 + jq_to_qmt(code)
    Sig->>Client: trader.order_stock(account, ...)
    Client->>QMT: 下单
    QMT-->>Client: 回调 on_stock_order()
    Client->>Sig: 追加到 signal_log deque
    Sig-->>Main: 返回执行结果
    Main-->>Remote: {success: true, order_id}

    Note over 用户,QMT: === 监控轮询 ===
    loop 每5秒
        Frontend->>Svr: GET /api/signals (X-Token)
        Svr-->>Frontend: signal_log 列表
        Frontend->>Frontend: 更新信号监控面板
    end
```

### 4. 前端模块依赖图

```mermaid
graph TB
    APP["app.js<br/>入口 & 初始化"] --> STATE["state.js<br/>全局状态"]
    APP --> API["api.js<br/>API 客户端"]
    APP --> UI["ui.js<br/>UI 工具"]
    APP --> CFG["config-panel.js<br/>配置面板"]
    APP --> MON["monitor.js<br/>信号监控"]
    APP --> DASH["dashboard.js<br/>账户仪表板"]

    CFG --> API
    CFG --> UI
    CFG --> STATE
    MON --> API
    MON --> UI
    MON --> STATE
    DASH --> API
    DASH --> UI
    DASH --> STATE
    API --> STATE

    HTML["index.html"] --> APP
    CSS["styles.css<br/>Coinbase 设计系统"] --> HTML
```

### 5. API 路由拓扑

```mermaid
graph LR
    subgraph "管理 API (main.py)"
        START["POST /api/start-server"]
        STOP["POST /api/stop-server"]
        INFO["GET /api/server-info"]
        HEALTH["GET /health"]
    end

    subgraph "静态路由 (server.py)"
        STATUS["GET /api/server-status"]
        CONN["GET /api/test-connection"]
        SIGNALS["GET /api/signals"]
        ASSET["GET /api/account-asset"]
    end

    subgraph "动态路由 (server.py 自动生成)"
        D1["POST /api/order_stock"]
        D2["POST /api/cancel_order"]
        D3["POST /api/query_stock_asset"]
        D4["POST /api/query_stock_orders"]
        D5["POST /api/query_stock_trades"]
        D6["POST /api/query_stock_positions"]
    end

    subgraph "信号 API (signal_handler.py)"
        RECV["POST /api/receive-signal"]
    end

    subgraph "转换 API"
        JQ["POST /api/convert/jq-to-qmt"]
        QJ["POST /api/convert/qmt-to-jq"]
    end

    管理_API -->|"后台线程控制"| 静态路由
    管理_API -->|"后台线程控制"| 动态路由
    管理_API -->|"后台线程控制"| 信号_API
```

---

## 后端架构

### 1. `config/settings.py` — 配置层
- 从环境变量读取：SERVER_HOST, SERVER_PORT, MINI_QMT_PATH, ACCOUNT_ID, SECRET_KEY, LOG_LEVEL, WECHAT_WEBHOOK_URL
- 提供合理的默认值
- 导出单例 settings 对象

### 2. `backend/constants.py` — 常量
- ANSI 颜色码（RED, GREEN, YELLOW, BLUE, RESET）
- 订单状态映射（48→未报, 56→已成 等）
- 买卖方向映射

### 3. `backend/logger.py` — 日志（qka 模式）
- `create_logger(name)` — 控制台 handler + 按日文件轮转（logs/YYYY-MM-DD.log）
- `WeChatHandler(logging.Handler)` — 企业微信 webhook 推送
- `add_wechat_handler(logger, level, webhook_url)`

### 4. `backend/utils.py` — 工具函数（qka 模式）
- `add_stock_suffix(code)` — 6位代码补全后缀（600000→600000.SH）
- `timestamp_to_datetime_string(ts)` — 时间戳转字符串
- `parse_order_type(order_type)` — 订单类型 int→中文

### 5. `backend/qmt_client.py` — QMT 连接层
遵循 qka `trade.py` 的精确模式：
- `MyXtQuantTraderCallback(XtQuantTraderCallback)` — 回调处理器
  - `on_disconnected()`, `on_stock_order()`, `on_stock_trade()`, `on_order_error()`, `on_cancel_error()`
  - 将事件追加到共享的 `signal_log` deque 中
- `create_trader(account_id, mini_qmt_path)` → `(trader, account, callback)`
  - `session_id = random.randint(100000, 999999)`（qka 模式）
  - `xt_trader = XtQuantTrader(path, session_id)`
  - `xt_trader.start()` → `xt_trader.connect()`
  - `account = StockAccount(account_id)`
  - `xt_trader.subscribe(account)`（qka 模式）
  - `xt_trader.register_callback(callback)`
- `jq_to_qmt(code)` / `qmt_to_jq(code)` — 聚宽格式转换
  - XSHE→SZ, XSHG→SH, XBJ→BJ

### 6. `backend/server.py` — 核心服务器（qka 模式）
`QMTServer` 类：
- `__init__(self, account_id, mini_qmt_path, host, port, token=None)`
- `generate_token()` — SHA256(MAC地址) 生成确定性 token
- `verify_token(x_token)` — FastAPI 依赖，校验 X-Token header
- `init_trader()` — 调用 create_trader，设置 self.trader, self.account, self.callback
- `convert_to_dict(obj)` — 递归转换 XtQuant 返回对象为 dict
- `convert_method_to_endpoint(method_name, method)` — 动态端点生成
  - 用 inspect 分析方法签名，排除 self 和 account
  - 动态创建 Pydantic BaseModel
  - 注册 `POST /api/{method_name}`，自动注入 account
- `setup_routes()` — 遍历 trader 所有公开方法，注册动态端点；注册静态路由
  - `GET /api/server-status` — 服务器状态
  - `GET /api/test-connection` — 测试连接（调用 query_stock_asset）
  - `GET /api/signals` — 获取信号历史
  - `GET /api/account-asset` — 获取账户资产
- `start()` — init_trader → setup_routes → uvicorn.run
- `stop()` — 清理

### 7. `backend/signal_handler.py` — 远程信号接收
`TradeSignal` Pydantic 模型：
- signal_id, stock_code (聚宽格式), direction (buy/sell), quantity, price (可选), order_type, strategy_name, timestamp

`SignalReceiver` 类：
- `receive_signal(signal)` → 验证 → 代码转换 → 下单 → 记录日志 → 返回结果
- 端点：`POST /api/receive-signal`（受 token 保护）

### 8. `backend/main.py` — 应用入口
- 创建 FastAPI app，配置 CORS 中间件
- 挂载 `../frontend/` 到静态文件
- `GET /` 提供 index.html
- 管理 API：`POST /api/start-server`, `POST /api/stop-server`, `GET /api/server-info`
- 后台线程运行 QMTServer
- CLI 入口：argparse 支持 --account --qmt-path --host --port --token

### 9. `backend/mock_xtquant/__init__.py` — Mock 层
- `MockTrader`: connect(), query_stock_asset() 返回模拟资产数据
- `MockStockAccount`: account_id 属性
- `MockData`: set_qmt_data_dir()
- `MockTraderCallback`: 基类

---

## 前端架构

### HTML 结构（5个区域，Coinbase 96px 区块间距）

```
.top-nav          — 固定顶部导航（Logo + 导航链接 + 主题切换）
.main-content
  #config         — 服务器配置表单（账号ID、QMT路径、主机、端口）
  #server-info    — 服务器状态卡片（状态、Token、连接信息）
  #signal-monitor — 信号监控面板（实时信号列表，核心区域）
  #jq-converter   — 聚宽代码转换工具
  #dashboard      — 账户仪表板（可用资金、持仓市值、总资产、当日盈亏）
.footer           — 页脚
```

### CSS 设计系统（来自 DESIGN.md）
- CSS 自定义属性：颜色、字体、间距、圆角、阴影
- 主色 #0052ff，仅用于主 CTA 和强调
- 按钮：pill 圆角（100px），44px 高度主按钮
- 卡片：24px 圆角，32px 内边距
- 字体：Inter（正文）、JetBrains Mono（数字）
- 亮/暗双主题（`[data-theme="dark"]`）
- 响应式：1024px / 768px / 480px 断点

### JS 模块设计

**`state.js`** — 全局状态
```
serverRunning, token, serverInfo, signals[], theme, pollingInterval
```

**`api.js`** — API 客户端
```
startServer(config), stopServer(), getServerInfo(), testConnection(token),
getSignals(token), getAccountAsset(token), convertJqToQmt(code), healthCheck()
```

**`ui.js`** — UI 工具
```
showMessage(text, type), updateServerInfo(data), resetServerInfo(),
addSignal(signal), clearSignals(), toggleTheme(), initTheme(),
disableForm(bool), updateDashboard(data), formatCurrency(n)
```

**`config-panel.js`** — 配置面板
- 表单提交处理
- 启动/停止服务器按钮逻辑
- 输入验证

**`monitor.js`** — 信号监控
- 实时信号列表渲染（时间戳、信号ID、股票代码、方向标签、数量、价格、状态）
- 每 5 秒轮询 `/api/signals`
- 最多保留 200 条
- 方向颜色：买入绿色、卖出红色

**`dashboard.js`** — 仪表板
- 4 张卡片：可用资金、持仓市值、总资产、当日盈亏
- 数字使用 JetBrains Mono 字体
- 点击"刷新"或连接测试成功后更新

---

## 实现顺序

### Phase 1: 项目基础搭建
1. 创建目录结构
2. `requirements.txt`（fastapi, uvicorn, pydantic, xtquant, pytest, pytest-asyncio, httpx）
3. `config/settings.py`

### Phase 2: 后端核心（qka 模式）
4. `backend/constants.py`
5. `backend/utils.py`
6. `backend/logger.py`
7. `backend/qmt_client.py`
8. `backend/mock_xtquant/__init__.py`
9. `backend/server.py`

### Phase 3: 后端信号功能
10. `backend/signal_handler.py`
11. `backend/main.py`

### Phase 4: 后端测试
12. `tests/test_client.py`
13. `tests/test_server.py`
14. `tests/test_signal_handler.py`

### Phase 5: 前端
15. `frontend/styles.css`
16. `frontend/index.html`
17. `frontend/js/state.js` → `api.js` → `ui.js`
18. `frontend/js/config-panel.js` → `monitor.js` → `dashboard.js`
19. `frontend/js/app.js`

### Phase 6: 集成与文档
20. 集成测试验证
21. `README.md`

---

## 验证方案

1. **后端测试**：`pytest tests/ -v` 验证所有单元测试通过
2. **Mock 模式启动**：在 macOS 上 `python -m backend.main --account test --qmt-path /tmp/mock` 验证服务器启动成功
3. **前端验证**：浏览器打开 `http://localhost:8000`，验证 UI 渲染和 API 交互
4. **信号测试**：`curl -X POST http://localhost:8000/api/receive-signal -H "X-Token: <token>" -H "Content-Type: application/json" -d '{"signal_id":"test-001","stock_code":"000001.XSHE","direction":"buy","quantity":100}'` 验证信号接收
5. **代码转换**：验证 jq_to_qmt 和 qmt_to_jq 转换正确性
