# QMT-Live-Assistant 深度思考（按项目现状更新）

> 本文档基于当前代码库实际状态重新梳理，区分「已实现」「部分实现」「待实施」，避免把规划推断写成现状。

---

## 一、商业化最佳方案

### 1.1 目标用户画像

项目当前解决的核心痛点：**让 QMT 实盘用户能够远程接收聚宽风格交易信号并自动下单，同时管理多个策略的独立资金和持仓。**

目标用户分三层：

| 层级 | 用户画像 | 规模估算 | 付费意愿 |
|------|---------|---------|---------|
| 个人量化交易者 | 用聚宽/米筐写策略，需要对接 QMT 实盘 | 数千~万级 | 中（¥299-999/年） |
| 小型量化团队 | 2-10人，管理多策略多账户 | 数百级 | 高（¥3000-10000/年） |
| 私募/机构 | 专业量化交易，需要风控、合规、审计 | 数十~百级 | 很高（¥20000+/年） |

### 1.2 商业模式选择

**推荐组合模型：Freemium + 功能分级 + 长期构建信号生态**

#### 模式 A：功能分级订阅（核心收入）

```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│              │  免费版      │  专业版       │  机构版       │
│              │  (Free)      │  (¥999/年)   │  (¥5000+/年) │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 策略数量     │  1 个        │  无限制       │  无限制       │
│ 信号接收     │  50条/天     │  无限制       │  无限制       │
│ 持仓跟踪     │  ✔           │  ✔           │  ✔           │
│ 代码转换     │  ✔           │  ✔           │  ✔           │
│ 风控规则     │  ✘           │  ✔           │  ✔           │
│ 数据分析面板 │  ✘           │  ✔           │  ✔           │
│ 微信/钉钉通知│  ✘           │  ✔           │  ✔           │
│ 历史回测集成 │  ✘           │  ✔           │  ✔           │
│ 多账户管理   │  ✘           │  ✘           │  ✔           │
│ 私有化部署   │  ✘           │  ✘           │  ✔           │
│ API 接入     │  ✘           │  有限         │  完整         │
│ 优先技术支持 │  ✘           │  48h响应      │  4h响应       │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

#### 模式 B：信号市场（长期愿景）

构建一个连接「策略开发者」和「实盘交易者」的平台：

- 策略开发者上传策略信号源
- 实盘用户订阅策略，按月/按盈利分成付费
- 平台抽成 20-30%
- 这是最具网络效应的模式，但需要先积累用户规模

#### 模式 C：企业定制（高客单价补充）

- 为私募/量化团队提供定制化部署
- 私有化部署 + 源码授权 + SLA 保障
- 单笔 3-10 万，年度维护费 20%

### 1.3 上市路径（Go-to-Market）

**阶段 1：种子用户获取（0→100 用户）**
- GitHub 开源积累 star（已有 README + 文档）
- 聚宽社区、迅投社区发布使用教程
- 微信量化群推广（README 中已有联系方式 `hotpotdaxia`）
- 提供免费版，降低使用门槛

**阶段 2：口碑增长（100→1000 用户）**
- 用户案例分享（实盘收益截图）
- B站/抖音教程视频
- 与聚宽官方合作，作为推荐的下单通道
- 推出专业版付费

**阶段 3：生态构建（1000→10000 用户）**
- 信号市场 Beta
- 与券商合作捆绑销售
- 机构客户直销
- 品牌建设：量化交易基础设施

### 1.4 关键成功要素

1. **稳定性 > 功能多**：实盘用户对稳定性的要求极高，一次 bug 可能导致巨大亏损。稳定性是第一卖点。
2. **信任建设**：交易软件涉及资金安全，需要：代码开源（可审计）、数据本地化、明确的隐私政策
3. **社区驱动**：开源社区贡献者可以成为付费用户，也可以帮助完善功能
4. **兼容性**：持续跟进 QMT SDK 更新，保持与最新版本兼容

---

## 二、项目现状与技术债务诊断

### 2.1 已验证的产品形态

经过近两个月的迭代，项目已经从「信号接收器」演进为「多策略订单执行器」：

- 支持启动/停止本地 FastAPI 交易服务器
- 支持多策略管理，每个策略独立资金、持仓、Token
- 支持聚宽风格的 4 种下单接口：`jukuan_order` / `jukuan_order_target` / `jukuan_order_value` / `jukuan_order_target_value`
- 实现了订单生命周期跟踪：乐观更新策略持仓 → 接收 xtquant 回调 → 轮询补偿 → 终态时按实际成交修正持仓
- 已实现桌面壳：系统托盘（pystray）+ 原生 WebView2 窗口（pywebview），可打包为单文件 exe
- 已实现账户资产、账户持仓、策略持仓的实时行情刷新与盈亏计算
- 前端仍基于原生 HTML/CSS/JS，保持 Coinbase 设计风格

### 2.2 当前真实技术栈

| 层 | 当前实际 | 说明 |
|----|---------|------|
| 后端框架 | FastAPI + uvicorn | 保持不变 |
| ORM / 数据库 | 无 | 策略、订单、持仓全部内存存储（dict） |
| 前端框架 | 原生 HTML + CSS + JS（ES Module） | 无 React/TS/Vite |
| 实时通信 | HTTP 轮询 | 前端轮询 `/api/orders`，后端每 5 秒轮询 QMT |
| 认证 | secrets.token_hex 随机 Token | 服务器一个 Token，每个策略一个 Token，无 JWT |
| 配置管理 | 简单 Settings 类 | 非 Pydantic Settings |
| 日志 | Python logging + 文件按日轮转 + 可选企业微信 Webhook | 非 structlog/Prometheus |
| 桌面壳 | pystray + pywebview | 已实现，pyinstaller.spec 已存在 |
| 测试 | pytest，171 个用例全部通过 | 缺少 pytest-cov，覆盖率数字需补充 |
| 部署 | PyInstaller 单文件 exe | 无 Docker / systemd |

### 2.3 仍然存在的核心技术债务

| 问题 | 严重程度 | 当前状态 | 影响 |
|------|---------|---------|------|
| 全内存存储，重启丢失策略/订单数据 | 🔴 严重 | 未解决 | 数据丢失，无法盘后分析 |
| 无数据库 / 持久化 | 🔴 严重 | 未解决 | 审计、历史回测、风控都无从谈起 |
| QMTServer 单体类职责仍过重（566 行） | 🟡 中等 | 部分缓解 | 策略/订单/聚宽下单已拆出，但路由注册仍集中在 server.py |
| 认证过于简单 | 🟡 中等 | 未解决 | 无 JWT/Refresh Token，策略 Token 一旦泄露无法吊销 |
| 前端无类型检查 | 🟡 中等 | 未解决 | 迭代效率低，重构风险高 |
| QMT 断连无自动重连 | 🔴 严重 | 未解决 | 信号丢失，实盘风险 |
| 缺少风控规则引擎 | 🟡 中等 | 未解决 | 无法限制单标的上限、日亏损等 |
| 无 WebSocket 实时推送 | 🟢 轻微 | 未解决 | 订单状态依赖轮询，延迟 1-5 秒 |
| 缺少 Docker / 系统服务化 | 🟢 轻微 | 未解决 | Windows 用户部署仍较繁琐 |
| 缺少结构化的可观测性（metrics/tracing） | 🟢 轻微 | 未解决 | 排障靠日志，无告警面板 |

### 2.4 值得保留的当前设计亮点

1. **订单状态机 + 持仓修正机制**
   - 下单时乐观更新策略持仓
   - `OrderTracker` 维护 pending / partial / filled / failed 状态
   - 接收 `on_stock_order` / `on_stock_trade` / `on_order_error` 回调
   - 后台 5 秒轮询 `query_stock_orders` 作为回调补偿
   - 终态时通过 `reconcile_position` 按实际成交修正持仓，避免乐观更新与真实成交不一致

2. **跨平台开发与测试**
   - 非 Windows 平台自动 fallback 到 `backend/mock_xtquant`
   - 测试可在 macOS/Linux 上完整运行（171 个用例通过）

3. **策略级隔离**
   - 每个策略独立 Token、独立资金、独立持仓
   - 远程下单携带策略 Token 即可自动关联

4. **桌面壳不发前端**
   - pywebview 直接加载本地 FastAPI 服务，前端代码无需改动
   - 关闭窗口最小化到托盘，符合实盘用户「交易机后台运行」的习惯

---

## 三、目标架构与演进路线

### 3.1 当前实际架构

```
┌─────────────────────────────────────────────────────────┐
│           Frontend (原生 HTML + CSS + JS)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Dashboard│ │ Strategy │ │ Monitor  │ │ Config   │   │
│  │  账户仪表 │ │ Manager  │ │ 订单监控 │ │ Panel    │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                         │  HTTP 轮询                     │
├─────────────────────────┼────────────────────────────────┤
│           Backend (FastAPI)                              │
│  ┌──────────────────────────────────────────────────┐   │
│  │  API Layer (路由 + 简单 Token 中间件)              │   │
│  └────────┬─────────┬──────────┬────────────────────┘   │
│           │         │          │                         │
│  ┌────────▼──┐ ┌───▼────┐ ┌──▼─────────┐               │
│  │ Strategy  │ │Trading │ │   Order    │               │
│  │ Service   │ │Service │ │  Tracker   │               │
│  │(内存模型) │ │(QMT连接)│ │(内存状态机)│               │
│  └─────┬─────┘ └───┬────┘ └──┬─────────┘               │
│        │            │         │                          │
│  ┌─────▼────────────▼─────────▼─────┐                   │
│  │      JukuanOrderHandler          │                   │
│  │  聚宽风格下单 + 代码转换          │                   │
│  └──────────────────────────────────┘                   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │           QMT Client Adapter                     │   │
│  │  XtQuantTrader / MockTrader / Callback           │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 3.2 长期目标架构

```
┌─────────────────────────────────────────────────────────┐
│           Frontend (React + TS + Vite)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Dashboard│ │ Strategy │ │ Monitor  │ │ Config   │   │
│  │          │ │ Manager  │ │ (WS实时) │ │ Panel    │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                         │  HTTP/WS                       │
├─────────────────────────┼────────────────────────────────┤
│           Backend (FastAPI)                              │
│  ┌──────────────────────────────────────────────────┐   │
│  │  API Layer (JWT + RateLimit + CORS + Validation)  │   │
│  └────────┬─────────┬──────────┬────────────────────┘   │
│           │         │          │                         │
│  ┌────────▼──┐ ┌───▼────┐ ┌──▼─────────┐               │
│  │ Strategy  │ │Trading │ │Signal/Order│               │
│  │ Service   │ │Service │ │  Service   │               │
│  └─────┬─────┘ └───┬────┘ └──┬─────────┘               │
│        │            │         │                          │
│  ┌─────▼────────────▼─────────▼─────┐                   │
│  │         Repository Layer         │                   │
│  │  StrategyRepo │ OrderRepo        │                   │
│  │  PositionRepo │ AuditLogRepo     │                   │
│  └───────────────┬──────────────────┘                   │
│                  │                                       │
│  ┌───────────────▼──────────────────┐                   │
│  │   SQLAlchemy 2.0 + Alembic       │                   │
│  │   SQLite (本地) / PostgreSQL (生产)│                   │
│  └──────────────────────────────────┘                   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │      QMT Adapter (连接池 + 自动重连 + 熔断)        │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 四、技术选型对比（当前 vs 目标）

| 层 | 当前实际 | 长期目标 | 原因 |
|----|---------|---------|------|
| 后端框架 | FastAPI | FastAPI（保持） | 性能好，生态成熟 |
| ORM | 无 | SQLAlchemy 2.0 + Alembic | 数据持久化，迁移管理 |
| 数据库 | 内存 dict | SQLite → PostgreSQL | 渐进式：单机用 SQLite，团队用 PG |
| 前端框架 | 原生 JS | React 18 + TypeScript | 类型安全，组件复用 |
| 前端构建 | 无 | Vite | 快速 HMR，Tree Shaking |
| UI 样式 | 手写 CSS | TailwindCSS + Coinbase Token | 保持设计系统，提升效率 |
| 实时通信 | HTTP 轮询 | WebSocket (FastAPI) | 实时推送订单状态 |
| 认证 | 随机 Token | JWT + Refresh Token | 标准安全方案，支持吊销 |
| 后台任务 | asyncio 轮询 | Celery / BackgroundTasks | 异步下单、通知 |
| 配置管理 | 简单 Settings 类 | Pydantic Settings | 类型安全，环境变量校验 |
| 代码质量 | 无 linter | Ruff + MyPy + pre-commit | 自动化规范 |
| 测试 | pytest | pytest + Playwright + 80%覆盖 | 完整测试金字塔 |
| 部署 | PyInstaller exe | Docker Compose + systemd | 一键部署，自启动 |
| 监控 | logging + 文件 | structlog + Prometheus | 结构化日志，可观测 |

---

## 五、分阶段实施计划（按当前状态重新划分）

### Phase 0：已完成的基线（✅）

- FastAPI 服务 + 原生 HTML/JS 前端
- miniQMT 连接与 XtQuant SDK 适配
- 多策略管理（CRUD、资金分配、持仓跟踪）
- 聚宽风格 4 种下单接口
- 订单状态机 + 乐观更新 + 回调/轮询修正
- 系统托盘 + WebView2 桌面窗口
- PyInstaller 打包配置
- mock_xtquant 跨平台测试支撑
- 171 个 pytest 用例

### Phase 1：数据持久化（🔴 最高优先级，尚未开始）

```
优先级：🔴 最高
风险：中等（需要兼容现有接口）
```

- 引入 SQLAlchemy 2.0，定义数据模型：Strategy, Order, Position, Account, AuditLog
- 引入 Alembic 做数据库迁移
- Repository 模式封装数据访问
- 阶段目标：策略、订单、持仓重启不丢失
- 兼容策略：保留内存模式作为测试 fallback，生产默认 SQLite

### Phase 2：服务层拆分与依赖注入（🟡 高优先级，部分完成）

```
优先级：🟡 高
风险：中等
```

- 已完成：策略管理拆出 `StrategyManager`、订单跟踪拆出 `OrderTracker`、聚宽下单拆出 `JukuanOrderHandler`
- 待完成：
  - 将 `server.py` 中剩余的路由注册逻辑拆到独立 router 模块
  - 引入 FastAPI `Depends` 做依赖注入
  - 将 QMT 连接、策略、订单作为可注入服务

### Phase 3：认证安全升级（🟡 高优先级，尚未开始）

```
优先级：🟡 高
风险：中等
```

- JWT Access Token + Refresh Token 替换简单 Token
- 策略 Token 支持吊销与轮换
- 登录接口与 Token 刷新接口
- 前端适配 JWT 过期自动刷新

### Phase 4：可靠性加固（🔴 最高优先级，尚未开始）

```
优先级：🔴 最高
风险：低（增量改进）
```

- QMT 断连自动重连 + 指数退避
- 订单处理队列化（确保高并发下不丢单）
- 操作审计日志（谁在何时做了什么）
- 异常告警：微信/钉钉/飞书多渠道通知
- 阶段目标：7×24 稳定运行

### Phase 5：前端现代化（🟡 高优先级，尚未开始）

```
优先级：🟡 高
风险：低（可渐进迁移）
```

- Vite + React 18 + TypeScript 项目初始化
- TailwindCSS 配置 Coinbase 设计 Token
- 渐进迁移：先迁移策略管理面板，再逐个迁移其他 tab
- WebSocket 接入实时订单推送
- 阶段目标：类型安全，组件化，实时更新

### Phase 6：高级功能（持续迭代，🟢 中优先级）

```
优先级：🟢 中
风险：低
```

- 风控规则引擎（单标的上限、止损止盈、日亏损限制）
- 策略绩效分析面板（夏普比率、最大回撤、收益曲线）
- 多账户支持
- 策略回测集成
- 代码转换插件系统（支持更多平台：米筐、掘金、TradingView）
- Docker 一键部署

---

## 六、数据库模型设计（待实施）

### 6.1 设计原则

基于当前代码的实际业务（多策略管理、聚宽风格下单、订单状态机、行情刷新盈亏），数据库设计遵循以下原则：

1. **事实与派生分离**：`total_asset`、`daily_pnl`、`current_price`、`market_value` 等行情或计算派生字段**不存储**，由 `positions` + `available_cash` + 实时行情计算得出；需要历史走势时才写入快照表。
2. **与 QMT 数据结构对齐**：数据库字段命名尽量与 `XtOrder`、`XtTrade`、`XtPosition`、`XtAsset` 等 QMT 结构保持一致（如 `order_sysid`、`traded_id`、`can_use_volume`、`frozen_cash`），减少适配层心智负担。
3. **订单状态与 QMT 状态解耦**：`orders.status` 是项目内部状态机（pending / partial / filled / failed / canceled），QMT 原始回调写入 `order_events`，避免 XtQuant SDK 状态码变化影响业务。
4. **账户持仓与策略持仓分离**：`account_positions` 缓存 QMT 查询到的账户原始持仓，用于风控、账户视图和持仓对账；`positions` 维护策略分配后的持仓。
5. **持仓数量拆分**：`quantity` 为总持仓，`available_quantity` 为可用持仓，`frozen_quantity` 为已委托未成交的冻结数量，三者满足 `quantity = available_quantity + frozen_quantity`。
6. **成交明细独立**：一笔委托可能分多笔成交，`order_fills` 记录每笔成交的价格、数量、时间，`orders` 只保留汇总。
7. **信号全量记录**：所有接收到的远程信号进入 `signal_logs`，无论是否成功下单，便于盘后审计与排障。
8. **Token 可轮换与吊销**：策略 Token 不直接存在 `strategies` 表中，而是独立到 `strategy_tokens`，支持多 Token、过期、吊销。
9. **资金字段用 DECIMAL**：所有金额类字段使用 `DECIMAL(19,4)`，避免浮点误差。
10. **软删除策略**：策略表使用 `deleted_at` 软删除，保留历史订单与审计关联。
11. **时间统一 UTC**：数据库中所有时间戳使用 UTC，前端展示时再转换本地时区。

### 6.2 表结构

```sql
-- 资金账号表
accounts
  id                  UUID PK
  name                VARCHAR(128)          -- 账户别名
  account_id          VARCHAR(64)  NOT NULL UNIQUE  -- 券商资金账号
  account_type        VARCHAR(32) NOT NULL DEFAULT 'STOCK'  -- 账号类型：STOCK / FUTURE / CREDIT / STOCK_OPTION / FUTURE_OPTION
  qmt_path            VARCHAR(512) NOT NULL  -- miniQMT userdata_mini 路径
  broker              VARCHAR(64)           -- 券商名称，如 国金、华泰
  is_active           BOOLEAN DEFAULT TRUE
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()

-- 策略表
strategies
  id                  UUID PK
  account_id          UUID FK -> accounts.id
  name                VARCHAR(128) NOT NULL
  description         TEXT
  enabled             BOOLEAN DEFAULT TRUE
  allocated_funds     DECIMAL(19,4) NOT NULL DEFAULT 0  -- 分配资金
  available_cash      DECIMAL(19,4) NOT NULL DEFAULT 0  -- 可用现金
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()
  deleted_at          TIMESTAMPTZ          -- 软删除

-- 策略 Token 表（支持轮换、过期、吊销）
strategy_tokens
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id
  token_hash          VARCHAR(128) NOT NULL UNIQUE  -- sha256(token)
  token_prefix        VARCHAR(16)                  -- 用于界面展示，如 abc***
  expires_at          TIMESTAMPTZ                  -- 过期时间，可空
  revoked_at          TIMESTAMPTZ                  -- 吊销时间，可空
  last_used_at        TIMESTAMPTZ
  created_at          TIMESTAMPTZ DEFAULT now()

-- 策略持仓表（只记录静态事实，不记录行情派生值）
positions
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id
  stock_code          VARCHAR(16) NOT NULL    -- QMT 格式，如 000001.SZ
  stock_name          VARCHAR(64)
  direction           VARCHAR(8)              -- 多空方向：long / short，期货适用；股票可为空
  quantity            INT NOT NULL DEFAULT 0  -- 总持仓
  available_quantity  INT NOT NULL DEFAULT 0  -- 可用持仓
  frozen_quantity     INT NOT NULL DEFAULT 0  -- 冻结持仓
  avg_cost            DECIMAL(19,4) NOT NULL DEFAULT 0  -- 加权成本价
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()

-- 账户持仓表（对应 QMT XtPosition，缓存账户原始持仓，用于风控、对账、账户视图）
account_positions
  id                  UUID PK
  account_id          UUID FK -> accounts.id
  stock_code          VARCHAR(16) NOT NULL       -- QMT 格式
  stock_name          VARCHAR(64)
  volume              INT NOT NULL DEFAULT 0     -- 总持仓数量（对应 XtPosition.volume）
  can_use_volume      INT NOT NULL DEFAULT 0     -- 可用数量（对应 XtPosition.can_use_volume）
  frozen_volume       INT NOT NULL DEFAULT 0     -- 冻结数量（对应 XtPosition.frozen_volume）
  on_road_volume      INT NOT NULL DEFAULT 0     -- 在途股份（对应 XtPosition.on_road_volume）
  yesterday_volume    INT NOT NULL DEFAULT 0     -- 昨夜拥股（对应 XtPosition.yesterday_volume）
  open_price          DECIMAL(19,4) DEFAULT 0    -- 开仓价/成本价（对应 XtPosition.open_price）
  direction           VARCHAR(8)                 -- 多空方向：long / short，期货适用
  snapshot_at         TIMESTAMPTZ NOT NULL       -- 该条缓存的查询时间
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()

-- 委托订单表（对应 QMT XtOrder）
orders
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id   -- 可为空，表示非策略下单
  account_id          UUID FK -> accounts.id
  external_order_id   VARCHAR(64)                -- QMT 返回的 order_id（int，以字符串存储）
  order_sysid         VARCHAR(64)                -- 柜台合同编号，QMT 撤单/精确查询需要
  stock_code          VARCHAR(16) NOT NULL       -- QMT 格式
  source_code         VARCHAR(24)                -- 信号源平台原始代码，如聚宽 000001.XSHE
  source_platform     VARCHAR(32)                -- 信号来源平台：joinquant / ricequant / tushare / manual / custom
  direction           VARCHAR(8) NOT NULL        -- buy / sell（对应股票买入/卖出）
  offset_flag         VARCHAR(16)                -- 交易操作：open / close / close_today / close_yesterday，期货/期权需要
  order_type          INT NOT NULL               -- QMT 委托类型，如 STOCK_BUY=23
  price_type          INT                        -- QMT price_type，如 LATEST_PRICE=5
  price               DECIMAL(19,4) DEFAULT 0    -- 委托价格，市价单为 0
  quantity            INT NOT NULL               -- 委托数量
  filled_quantity     INT NOT NULL DEFAULT 0     -- 累计成交数量
  filled_price        DECIMAL(19,4) DEFAULT 0    -- 加权成交均价
  filled_amount       DECIMAL(19,4) DEFAULT 0    -- 累计成交金额
  status              VARCHAR(16) NOT NULL DEFAULT 'pending'
                        -- pending / partial / filled / failed / canceled
  status_msg          TEXT                       -- QMT 委托状态描述（如废单原因）
  error_code          VARCHAR(32)                -- QMT 错误码
  error_msg           TEXT                       -- 错误描述
  placed_at           TIMESTAMPTZ DEFAULT now()  -- 本地创建时间
  exchange_order_time TIMESTAMPTZ                -- QMT 返回的报单时间
  resolved_at         TIMESTAMPTZ                -- 到达终态时间
  strategy_name       VARCHAR(128)               -- 写入 QMT 的策略名称
  order_remark        VARCHAR(64)                -- 写入 QMT 的委托备注（当前用于存放 source_code）
  request_payload     JSONB                      -- 原始请求参数
  response_payload    JSONB                      -- QMT 返回结果
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()

-- 成交明细表
order_fills
  id                  UUID PK
  order_id            UUID FK -> orders.id
  fill_no             VARCHAR(64)                -- 成交编号，QMT 如有则记录
  quantity            INT NOT NULL
  price               DECIMAL(19,4) NOT NULL
  amount              DECIMAL(19,4) NOT NULL     -- quantity * price
  filled_at           TIMESTAMPTZ NOT NULL
  created_at          TIMESTAMPTZ DEFAULT now()

-- 订单事件表（记录状态流转与 QMT 回调原始数据）
order_events
  id                  UUID PK
  order_id            UUID FK -> orders.id
  event_type          VARCHAR(32) NOT NULL
                        -- placed / callback / trade / error / poll / canceled / filled / failed
  from_status         VARCHAR(16)
  to_status           VARCHAR(16)
  payload             JSONB                      -- 回调或轮询的原始数据
  source              VARCHAR(32)                -- xtquant_callback / poll / manual
  created_at          TIMESTAMPTZ DEFAULT now()

-- 信号日志表（所有远程信号）
signal_logs
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id
  endpoint            VARCHAR(64) NOT NULL       -- 如 /api/jukuan_order_target
  source_platform     VARCHAR(32)                -- 信号来源平台：joinquant / ricequant / tushare / manual / custom
  source_ip           VARCHAR(64)
  payload             JSONB NOT NULL             -- 完整请求体
  processed_order_id  UUID FK -> orders.id       -- 生成的订单，未生成为空
  error_msg           TEXT                       -- 处理失败原因
  received_at         TIMESTAMPTZ DEFAULT now()
  created_at          TIMESTAMPTZ DEFAULT now()

-- 账户资产快照表（对应 QMT XtAsset，用于绩效分析、收益曲线）
account_snapshots
  id                  UUID PK
  account_id          UUID FK -> accounts.id
  total_asset         DECIMAL(19,4) NOT NULL
  available_cash      DECIMAL(19,4) NOT NULL
  frozen_cash         DECIMAL(19,4) NOT NULL DEFAULT 0  -- 冻结金额
  market_value        DECIMAL(19,4) NOT NULL
  daily_pnl           DECIMAL(19,4) NOT NULL
  captured_at         TIMESTAMPTZ NOT NULL
  created_at          TIMESTAMPTZ DEFAULT now()

-- 策略资产快照表
strategy_snapshots
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id
  available_cash      DECIMAL(19,4) NOT NULL
  total_asset         DECIMAL(19,4) NOT NULL     -- 可用现金 + 持仓市值
  daily_pnl           DECIMAL(19,4) NOT NULL
  captured_at         TIMESTAMPTZ NOT NULL
  created_at          TIMESTAMPTZ DEFAULT now()

-- 风控规则表
risk_rules
  id                  UUID PK
  strategy_id         UUID FK -> strategies.id   -- 空表示账户级规则
  account_id          UUID FK -> accounts.id
  rule_type           VARCHAR(32) NOT NULL
                        -- max_position_value / max_single_stock_ratio /
                        -- daily_loss_limit / max_order_value / price_deviation
  params              JSONB NOT NULL             -- 规则参数
  enabled             BOOLEAN DEFAULT TRUE
  created_at          TIMESTAMPTZ DEFAULT now()
  updated_at          TIMESTAMPTZ DEFAULT now()

-- 风控触发记录表
risk_events
  id                  UUID PK
  rule_id             UUID FK -> risk_rules.id
  strategy_id         UUID FK -> strategies.id
  order_id            UUID FK -> orders.id
  signal_log_id       UUID FK -> signal_logs.id
  triggered_value     JSONB                      -- 触发时的实际值
  action              VARCHAR(16) NOT NULL       -- block / warn
  created_at          TIMESTAMPTZ DEFAULT now()

-- 账号状态事件表（对应 QMT XtAccountStatus，用于监控、告警、自动重连决策）
account_status_events
  id                  UUID PK
  account_id          UUID FK -> accounts.id
  account_type        INT                        -- QMT 账号类型
  status              INT NOT NULL               -- QMT 账号状态枚举值
  status_name         VARCHAR(64)                -- 状态名称：OK / FAIL / DISCONNECTED / CLOSED 等
  event_source        VARCHAR(32)                -- callback / poll / manual
  payload             JSONB                      -- QMT 原始状态数据
  created_at          TIMESTAMPTZ DEFAULT now()

-- 操作审计表
audit_logs
  id                  UUID PK
  actor_type          VARCHAR(32)                -- 操作者类型：user / server_token / strategy_token / system
  actor_id            VARCHAR(128)               -- 操作者标识（用户ID 或 Token 前缀）
  actor_token_hash    VARCHAR(128)               -- 如为 Token 操作，记录 Token hash
  action              VARCHAR(64) NOT NULL       -- create_strategy / start_server / delete_strategy
  resource_type       VARCHAR(64)                -- strategy / account / order
  resource_id         VARCHAR(64)
  detail              JSONB
  ip                  VARCHAR(64)
  user_agent          TEXT
  created_at          TIMESTAMPTZ DEFAULT now()
```

### 6.3 关键索引

```sql
-- 按业务查询频率设计
CREATE INDEX idx_strategies_account_id ON strategies(account_id);
CREATE INDEX idx_strategies_deleted_at ON strategies(deleted_at) WHERE deleted_at IS NULL;

CREATE INDEX idx_strategy_tokens_hash ON strategy_tokens(token_hash);
CREATE INDEX idx_strategy_tokens_strategy_id ON strategy_tokens(strategy_id);
CREATE INDEX idx_strategy_tokens_active ON strategy_tokens(strategy_id, revoked_at, expires_at)
    WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now());

CREATE INDEX idx_positions_strategy_id ON positions(strategy_id);
CREATE UNIQUE INDEX idx_positions_strategy_stock_direction ON positions(strategy_id, stock_code, COALESCE(direction, ''));

CREATE INDEX idx_account_positions_account_id ON account_positions(account_id);
CREATE UNIQUE INDEX idx_account_positions_account_stock_direction ON account_positions(account_id, stock_code, COALESCE(direction, ''));
CREATE INDEX idx_account_positions_snapshot_at ON account_positions(snapshot_at DESC);

CREATE INDEX idx_orders_strategy_id ON orders(strategy_id);
CREATE INDEX idx_orders_account_id ON orders(account_id);
CREATE INDEX idx_orders_external_order_id ON orders(external_order_id);
CREATE INDEX idx_orders_order_sysid ON orders(order_sysid);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_placed_at ON orders(placed_at DESC);
CREATE INDEX idx_orders_strategy_placed ON orders(strategy_id, placed_at DESC);

CREATE INDEX idx_order_fills_order_id ON order_fills(order_id);
CREATE INDEX idx_order_events_order_id ON order_events(order_id);
CREATE INDEX idx_order_events_created_at ON order_events(created_at);

CREATE INDEX idx_signal_logs_strategy_id ON signal_logs(strategy_id);
CREATE INDEX idx_signal_logs_received_at ON signal_logs(received_at DESC);
CREATE INDEX idx_signal_logs_order_id ON signal_logs(processed_order_id);

CREATE INDEX idx_account_snapshots_account_id ON account_snapshots(account_id);
CREATE INDEX idx_account_snapshots_captured_at ON account_snapshots(captured_at DESC);
CREATE INDEX idx_strategy_snapshots_strategy_id ON strategy_snapshots(strategy_id);
CREATE INDEX idx_strategy_snapshots_captured_at ON strategy_snapshots(captured_at DESC);

CREATE INDEX idx_account_status_events_account_id ON account_status_events(account_id);
CREATE INDEX idx_account_status_events_created_at ON account_status_events(created_at DESC);

CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_actor ON audit_logs(actor_type, actor_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
```

### 6.4 与当前内存模型及 QMT 数据结构的映射

| 当前内存 / QMT 结构 | 对应数据库表 | 说明 |
|-------------------|-------------|------|
| `StrategyManager._strategies` | `strategies` + `positions` | 拆分持仓为独立表 |
| `Strategy.token` | `strategy_tokens` | 支持多 Token、吊销、过期 |
| `OrderTracker._orders` | `orders` + `order_fills` + `order_events` | 事实与事件分离 |
| `Strategy.trading_records` | `orders` + `signal_logs` | 交易记录由订单表承载，信号原始数据独立 |
| `XtOrder`（QMT 委托） | `orders` + `order_events` | `external_order_id` 对应 `order_id`，`order_sysid` 对应柜台合同编号 |
| `XtTrade`（QMT 成交） | `order_fills` | `fill_no` 对应 `traded_id` |
| `XtPosition`（QMT 持仓） | `account_positions` | 缓存账户原始持仓；`positions` 维护策略分配后的持仓 |
| `XtAsset`（QMT 资产） | `account_snapshots` | 历史快照用于绩效，实时值仍走 QMT 查询 |
| `XtAccountStatus`（QMT 账号状态） | `account_status_events` | 记录连接/断开/失败等状态变化，用于监控告警 |

### 6.5 核心设计决策说明

1. **为什么 `orders` 和 `trading_records` 不拆成两张表？**
   - 当前 `trading_records` 只是订单的轻量副本。一旦引入持久化，完全可以用 `orders` 承载所有交易记录，并通过 `order_events` 记录状态流转。避免数据冗余和同步问题。

2. **为什么 `positions` 不存 `market_value` 和 `daily_pnl`？**
   - 这两个值依赖实时行情（`current_price`、`preClose`），行情变化时不应触发数据库写入。由 `list_all_enriched` 实时计算即可；需要历史曲线时写入 `strategy_snapshots`。

3. **为什么需要 `account_positions` 表？**
   - 风控必须基于账户真实持仓，而不是策略分配持仓。`account_positions` 缓存 `query_stock_positions()` 的原始结果，同时用于与 `positions` 对账，发现策略持仓与账户持仓不一致时触发告警。

4. **为什么 `orders` 要同时存 `external_order_id` 和 `order_sysid`？**
   - `external_order_id` 对应 QMT `XtOrder.order_id`，是我们下单时返回的本地订单号；`order_sysid` 对应 `XtOrder.order_sysid`，是券商柜台合同编号。撤单接口 `cancel_order_stock_sysid` 和精确查询需要 `order_sysid`。

5. **为什么需要 `account_status_events` 表？**
   - QMT 有 `on_account_status` 回调和 `query_account_status` 接口，状态包括正常、失败、断开、收盘后等。持久化这些事件后，可以实现：断连告警、自动重连决策、盘后自动切换监控模式。

6. **为什么需要 `signal_logs.source_platform` 和 `orders.source_platform`？**
   - 信号层面记录来源，便于统计各平台信号量；订单层面记录来源，便于在订单监控中按平台筛选。

7. **为什么 `orders` 需要 `offset_flag`？**
   - 当前项目只做股票，用 `direction=buy/sell` 足够。但 QMT `XtOrder` 有 `offset_flag` 字段区分股票买卖、期货开平仓、期权买卖等。预留该字段可避免未来支持期货/期权时改表结构。

8. **为什么 `orders` 需要 `status_msg` 和 `error_code`？**
   - `XtOrder.status_msg` 包含委托状态描述（如废单原因），`XtOrderError.error_id` 是错误码。`error_msg` 只描述错误，`status_msg` 可描述正常状态；`error_code` 便于按错误类型聚合统计。

9. **为什么 `account_snapshots` 要存 `frozen_cash`？**
   - `XtAsset` 有 `frozen_cash` 字段，记录冻结资金。对于风控（如日可用资金下限）和绩效分析，冻结资金是必要输入。

10. **为什么 `orders.status` 与 QMT 状态码解耦？**
    - XtQuant SDK 的 `order_status` 可能随版本变化，且部分状态（如部分成交后撤单）需要业务判断。内部状态机统一为 5 种，QMT 原始状态存入 `order_events`。

11. **为什么 `positions` 和 `account_positions` 都有 `direction` 字段？**
    - 股票策略通常不需要 direction，该字段为空；期货/期权同一合约可能同时持有多空头寸，必须通过 `(stock_code, direction)` 唯一标识一条持仓。Unique index 中使用 `COALESCE(direction, '')` 兼容股票场景。

12. **为什么 `audit_logs` 用 `actor_type` / `actor_id` 而不是 `user_id`？**
    - 当前项目没有用户系统，操作者可能是服务器 Token、策略 Token 或系统任务。`actor_type` 区分来源类型，`actor_id` 记录可识别的操作者，`actor_token_hash` 在需要时追溯具体 Token。未来引入用户系统后，可新增 `user_id` 字段或把用户映射到 actor_id。

---

## 七、其他需要思考的方面

### 7.1 合规与法律风险

- **证券监管**：提供交易下单工具是否需要牌照？需要咨询律师。通常自动化下单工具属于「程序化交易」范畴，需遵守交易所相关规定。
- **免责声明**：软件必须明确声明「不构成投资建议」，因软件故障导致的交易损失需有明确的责任界定。
- **数据隐私**：用户的策略、持仓、交易记录属于高度敏感数据。数据必须本地化存储，云端同步需端到端加密。
- **开源协议**：选择合适的开源协议。如果商用，考虑 AGPL（要求衍生作品也开源）或 BSL（Business Source License，限制商用）。

### 7.2 竞品分析

| 竞品 | 形态 | 优势 | 劣势 |
|------|------|------|------|
| QMT 自带功能 | 桌面软件 | 官方支持、稳定 | 无远程信号、单机操作 |
| 迅投 VN Trader | 开源框架 | 社区活跃、功能全 | 学习曲线陡、无 Web UI |
| Qlib（微软） | AI量化框架 | AI能力强 | 不直接支持 QMT 交易 |
| 通达信/同花顺 | 桌面软件 | 用户量大 | 不支持程序化定制 |

**差异化定位**：我们做的是「连接层」——连接策略平台（聚宽等）和交易终端（QMT），并提供多策略管理。这个细分目前竞品较少。

### 7.3 技术风险

1. **QMT SDK 变更风险**：XtQuant SDK 是闭源的，随时可能变更接口。对策：适配层隔离，定期回归测试。
2. **Windows 强依赖**：QMT 仅运行在 Windows，限制了部署灵活性。对策：探索 WINE/虚拟机方案，或提供树莓派级别的小型 Windows 设备。
3. **单点故障**：本地服务器宕机则无法接收信号。对策：支持主备模式，健康检查 + 自动切换。
4. **网络攻击面**：开放 HTTP 端口接收远程信号，可能被攻击。对策：IP 白名单、HTTPS、请求签名验证。
5. **数据丢失风险**：当前全内存存储，进程重启即丢失策略与订单历史。对策：尽快引入数据库持久化。

### 7.4 运营与维护成本

- **技术支持**：免费用户通过 GitHub Issues 自助，付费用户提供微信/企业微信支持
- **兼容性测试**：每个 QMT 版本更新后需回归测试（需维护 Windows 测试环境）
- **文档维护**：使用指南、API 文档、FAQ、视频教程需要持续更新
- **服务器成本**：初期仅需用户本地运行，无服务器成本。信号市场阶段需云端中继服务器。

### 7.5 合作伙伴生态

- **上游（信号源）**：聚宽、米筐、掘金、TradingView、自定义 Webhook
- **下游（券商）**：国金证券、华泰证券、中信证券等支持 QMT 的券商
- **工具链**：数据供应商（Wind、Tushare）、回测框架（Backtrader、Zipline）
- **社区**：知乎量化圈、掘金量化社区、聚宽论坛

### 7.6 增长飞轮

```
开源免费工具 → 获取用户 → 部分转化为付费用户
                              ↓
                    用户贡献策略到信号市场
                              ↓
                    更多用户被信号吸引加入
                              ↓
                    策略开发者获得收入激励
                              ↓
                    产出更多优质策略...
```

### 7.7 放弃的方向（不做）

- ✘ 不做策略研发（不跟聚宽/米筐竞争）
- ✘ 不做行情数据服务（不跟 Wind/Tushare 竞争）
- ✘ 不做回测平台（专注实盘执行）
- ✘ 不做移动端 App（Web 响应式足够，移动端交易风险高）
- ✘ 不碰加密货币（专注 A 股市场，合规清晰）

### 7.8 关键指标（OKR）

**6个月目标：**
- 1000 个活跃安装
- 100 个付费用户（转化率 10%）
- GitHub 500+ stars
- 系统可用性 > 99.5%

**12个月目标：**
- 5000 个活跃安装
- 500 个付费用户
- 信号市场 MVP 上线，10 个策略开发者入驻
- 月经常性收入 (MRR) > ¥50,000

### 7.9 建议的定价实验

初期不要定死价格，通过 A/B 测试找到最优定价点：

- 方案 A：¥299/年专业版
- 方案 B：¥499/年专业版
- 方案 C：¥999/年专业版

同时测试不同功能组合对转化率的影响。最优可能是一次性买断（¥980 终身）+ 年度维护（¥199/年）的组合。

---

## 八、桌面化决策复盘

### 8.1 已实现的方案

当前项目已经采纳了「轻量桌面壳，不重写前端」的路线：

- `backend/tray.py`：基于 `pystray` 的系统托盘，支持打开界面、复制 Token、退出
- `backend/window.py`：基于 `pywebview` 的 WebView2 原生窗口，关闭时最小化到托盘
- `backend/main.py`：支持 `--tray` / `--window` 两种桌面壳启动方式，打包后自动进入窗口模式
- `pyinstaller.spec`：单文件 exe 打包配置已就绪

### 8.2 为什么不改为纯桌面应用

1. **成本收益不成正比**：用 WPF/Qt 重写前端至少 2-3 个月，但用户需要的功能 HTML 完全能实现。
2. **Web 能力不输桌面**：CSS 动画、WebSocket 实时推送、LocalStorage 持久化、Notification API 系统通知——现代浏览器都有。
3. **量化交易者天然接受 Web**：聚宽、米筐、TradingView 全是 Web。目标用户对 Web 界面没有抵触。
4. **远程访问是不可替代的杀手特性**：桌面应用很难做远程访问，而 Web 架构天然支持。很多用户就是为了「手机看信号」才选这个工具。
5. **保持开源的透明性**：Web 前端代码在浏览器 F12 即可审查，符合开源的信任诉求。

### 8.3 后续可感知的商业化包装

| 手法 | 实现 | 成本 |
|------|------|------|
| 单文件 exe | PyInstaller 打包 | 低 |
| 自定义安装程序 | NSIS / Inno Setup | 低 |
| 品牌化 System Tray | pystray + 自定义图标 | 低 |
| 开机自启 | 注册表 Run key / 计划任务 | 低 |
| 付费 License 激活 | 在线激活码验证 | 中 |
| 自动更新 | GitHub Release 检测 | 中 |
| 专属安装目录 | `C:\Program Files\QMT-LA\` | 低 |

---

## 九、下一步最关键的三件事

1. **数据持久化**：引入 SQLAlchemy + SQLite，把策略、订单、持仓落到数据库。这是从「玩具」到「生产工具」的分水岭。
2. **QMT 断连自动重连**：实盘环境下网络波动或 QMT 重启是常态，没有自动重连意味着丢单。
3. **认证升级**：JWT + Refresh Token + 策略 Token 吊销，为付费版和多用户场景打基础。

这三件事做完，项目才具备商业化所需的稳定性和安全性基线。
