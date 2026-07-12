➕V 一起探讨：hotpotdaxia

# QMT Live Assistant

基于 Python 服务器 + 原生 HTML 前端的 miniQMT 量化交易助手。UI 设计采用 Coinbase 网站的风格。

## 如何使用
1. [QMT-Live-Assistant 使用指南](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/qmt-live-assistant-usage/content.md)
2. [聚宽如何发送信号给 QMT-Live-Assistant](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/jq-send-signal-to-qmt/content.md)

## 功能

- 连接 miniQMT 交易终端（迅投 XtQuant SDK）
- 启动/停止本地交易服务器
- 测试连接并获取账户资产（可用资金、持仓市值、总资产、当日盈亏）
- 多策略管理：创建多个交易策略，各自独立分配资金、跟踪持仓、接收聚宽风格下单
- 策略概览：查看各策略的可用资金、总资产、当日盈亏与订单数量；点击策略卡片展开持仓明细表，点击订单数量可跳转至订单列表并自动筛选对应策略
- 聚宽风格下单：远程策略服务器通过 `/api/jukuan_order*` 接口下单，自动关联策略并更新持仓
- 策略 Token 认证：每个策略拥有独立 Token，远程下单携带策略 Token 即可关联
- 数据持久化：策略、持仓、订单、信号日志等默认落库 SQLite，服务重启数据不丢失
- 实时订单监控面板，支持按日期、策略和状态筛选；列表底部展示当前筛选结果条数
- 信号日志面板，记录远程策略服务器发送到本地下单接口的请求与处理结果，支持按日期、策略和状态（异常/正常）筛选，默认展示异常信号，便于排查问题
- 从 QMT 获取实时行情刷新策略持仓市值和当日盈亏
- 聚宽格式 ↔ QMT 格式代码转换；策略持仓统一持久化为 QMT 格式（.SZ/.SH/.BJ）
- 聚宽风格下单：支持按数量/金额/目标仓位下单，无持仓时自动通过 QMT 全推行情获取最新价
- 亮/暗双主题切换
- 随机 Token 认证（secrets.token_hex），保护所有交易 API 端点

## 技术栈

- **后端**: Python 3.10+ / FastAPI / uvicorn / xtquant SDK / SQLAlchemy 2.0 / Alembic / SQLite
- **前端**: 原生 HTML + CSS + JS（ES Module）
- **设计**: Coinbase 设计风格

## 项目结构

```
QMT-live-assistant/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── server.py            # QMTServer 核心
│   ├── qmt_client.py        # miniQMT 连接
│   ├── order_tracker.py     # 订单状态跟踪
│   ├── strategy_manager.py  # 策略管理器（多策略支持）
│   ├── models/              # Pydantic / dataclass 领域模型
│   │   ├── strategy.py
│   │   └── order.py
│   ├── db/                  # 数据库模型、Repository、迁移
│   │   ├── base.py
│   │   ├── models/
│   │   ├── repositories/
│   │   └── migrations/
│   ├── utils.py             # 工具函数（含 jq_to_qmt / qmt_to_jq / normalize_to_qmt）
│   ├── jukuan_orders.py     # 聚宽风格下单
│   ├── logger.py            # 日志系统
│   ├── constants.py         # 常量定义
│   ├── qmt_xtconstant.py    # QMT 常量
│   └── mock_xtquant/        # 非 Windows 平台的 mock
├── frontend/
│   ├── index.html           # 单页应用
│   ├── styles.css           # Coinbase 风格
│   └── js/
│       ├── app.js           # 入口
│       ├── state.js         # 状态管理
│       ├── api.js           # API 客户端
│       ├── ui.js            # UI 工具
│       ├── config-panel.js  # 配置面板
│       ├── monitor.js       # 订单监控
│       ├── dashboard.js     # 仪表板
│       ├── strategy.js      # 策略管理面板
│       └── toast.js         # Toast 通知
├── config/
│   └── settings.py
├── tests/
│   ├── test_client.py
│   ├── test_server.py
│   ├── test_signal_handler.py
│   ├── test_strategy_manager.py
│   ├── test_jukuan_orders.py
│   ├── test_utils.py
│   └── repositories/        # Repository 层测试
│       ├── test_strategy_repository.py
│       ├── test_order_repository.py
│       └── test_signal_log_repository.py
├── requirements.txt
└── README.md
```

## 安装

前提：安装了 python 环境和 QMT

```bash
pip install -r requirements.txt
alembic upgrade head
```

> **注意**: `xtquant` SDK 仅在 Windows 上可用。在 macOS/Linux 上，项目自动使用 mock 实现进行开发和测试。

## 数据持久化

默认使用 SQLite 存储策略、持仓、订单、信号日志等数据（共 7 张表，包括 accounts、strategies、positions、orders、strategy_tokens、order_events、signal_logs）。首次运行前执行：

```bash
alembic upgrade head
```

数据文件位于 `./data/qmt_live_assistant.db`。

可通过环境变量切换模式：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PERSISTENCE_MODE` | `sqlite` | `sqlite` 或 `memory` |
| `DATABASE_URL` | `sqlite:///./data/qmt_live_assistant.db` | SQLAlchemy 数据库 URL |

测试直接实例化 InMemory Repository 或使用内存 SQLite，无需执行迁移。

## 运行

### 原生桌面窗口模式（Windows 推荐）

启动后弹出原生 WebView2 窗口，关闭窗口最小化到系统托盘：

```bash
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini" --window
```

右键托盘图标可打开界面、复制 Token、退出服务。

### 桌面壳 / 托盘模式

系统托盘 + 自动打开浏览器：

```bash
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini" --tray
```

### 前端界面模式

启动管理界面，通过浏览器配置和监控：

```bash
python -m backend.main --port 8000
```

浏览器打开 `http://localhost:8000`，填写账户ID和QMT路径，点击"启动服务器"。

### CLI 模式

跳过前端，直接启动交易服务器：

```bash
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini" --port 8000
```

启动后控制台会打印 Token，远程信号服务器使用此 Token 调用 API。

### 启动方式速查

| 命令 | 模式 | 窗口 | 托盘 |
|------|------|------|------|
| `--window` | 原生桌面窗口 | WebView2 | 系统托盘 |
| `--tray` | 桌面壳 | 外部浏览器 | 系统托盘 |
| `--port 8000` | 前端界面 | 外部浏览器 | ✘ |
| `--account … --qmt-path …` | CLI 服务 | ✘ | ✘ |


## 策略管理

服务器启动后，可在「配置」tab 中管理策略：

1. **创建策略**：设置策略名称（必填）、描述、分配金额（必填），可选从账户现有持仓中分配数量到该策略
2. **获取 Token**：每个策略自动生成独立 Token，用于远程聚宽风格下单认证
3. **下单关联**：远程策略服务器用策略 Token 调用 `/api/jukuan_order*` 等接口，订单自动关联到该策略；target/value 类接口会基于策略自身持仓和可用资金计算委托数量，卖出时校验策略可用持仓，买入时校验策略可用资金
4. **持仓跟踪**：策略持仓统一以 QMT 格式（.SZ/.SH/.BJ）持久化，仅持久化股票代码、名称、数量和成本价（avg_cost），现价、市值、当日盈亏等行情数据在请求时从 QMT 实时获取；买入委托未成交前不会在持仓列表中显示，成交后才会出现对应持仓
5. **成本价与盈亏计算**：
   - 新建策略或人工更新持仓时，取 xtquant 当日开盘价作为成本基准，持仓标记为「今日买入」；加仓时自动计算加权均价
   - 持仓盈亏 `total_pnl` = 策略自身分摊市值 − 成本价 × 数量，按策略持仓占账户总持仓比例分摊市值
   - 当日盈亏 `daily_pnl` 拆分为两部分计算：昨日已有持仓按「现价 − 昨日收盘价」计算，今日买入持仓按「现价 − 买入成本」计算
   - 每日首次刷新行情时自动跨日合并：前一天的「今日买入」部分合并为「昨日持仓」，并使用昨日收盘价作为新的成本基准
6. **行情刷新**：点击「刷新行情」从 QMT 拉取实时数据，计算策略持仓市值、现价、持仓盈亏和当日盈亏
7. **策略概览**：在「QMT账号」tab 查看各策略的资产概览卡片，卡片展示持仓数量与订单数量；点击卡片查看该策略的持仓明细表（持仓/可用、成本/现价、市值、累计盈亏、当日盈亏，与账户持仓列一致）；点击订单数量可跳转至「买卖监控」并自动筛选该策略的订单
8. **持仓/资金校验**：策略 Token 下单时，系统按策略级别的持仓和可用资金进行校验，而非账户整体；卖出数量不可超过策略对应股票的可用持仓，按金额买入不可超过策略可用资金


## API 参考

### 管理 API

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/health` | 无 | 健康检查 |
| GET | `/api/server-info` | 无 | 服务器状态（不含 Token） |
| POST | `/api/start-server` | 无 | 启动服务器，返回 Token |
| POST | `/api/stop-server` | X-Token | 停止服务器 |

### 策略管理 API（需要 X-Token 头，主 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategies` | 列出所有策略及数据 |
| POST | `/api/strategies` | 创建策略，返回策略及 Token |
| PUT | `/api/strategies/{id}` | 编辑策略 |
| DELETE | `/api/strategies/{id}` | 删除策略 |
| POST | `/api/strategies/{id}/toggle` | 切换启用/禁用 |
| POST | `/api/strategies/refresh` | 从 QMT 刷新策略持仓行情 |

### 交易 API（需要 X-Token 头，主 Token 或策略 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/test-connection` | 测试连接，返回资产数据 |
| GET | `/api/account-asset` | 账户资产 |
| GET | `/api/account-positions` | 账户持仓明细 |
| GET | `/api/orders` | 订单历史（支持 `?status=&strategy_name=&start_date=&end_date=`） |
| GET | `/api/signal-logs` | 信号日志（支持 `?status=&strategy_name=&start_date=&end_date=`） |
| POST | `/api/convert/jq-to-qmt` | 聚宽→QMT 转换 |
| POST | `/api/convert/qmt-to-jq` | QMT→聚宽 转换 |
| POST | `/api/jukuan_order` | 聚宽风格按数量下单 |
| POST | `/api/jukuan_order_target` | 聚宽风格目标持仓下单 |
| POST | `/api/jukuan_order_value` | 聚宽风格按金额下单 |
| POST | `/api/jukuan_order_target_value` | 聚宽风格目标市值下单 |

### 动态端点（自动生成）

以下端点根据 XtQuantTrader 方法自动生成，所有端点需要 X-Token：

- `POST /api/order_stock` — 下单
- `POST /api/cancel_order` — 撤单
- `POST /api/query_stock_asset` — 查询资产
- `POST /api/query_stock_orders` — 查询委托
- `POST /api/query_stock_trades` — 查询成交
- `POST /api/query_stock_positions` — 查询持仓

### 聚宽下单格式

远程策略服务器使用策略 Token 调用 `/api/jukuan_order`：

**使用策略 Token（推荐）**：订单自动关联到对应策略，执行后自动更新策略持仓和资金。

```json
{
  "security": "000001.XSHE",
  "amount": 100,
  "side": "long"
}
```

请求头：`X-Token: <策略Token>`

- `security`：证券代码，支持聚宽格式（`.XSHE`/`.XSHG`/`.XBJ`）或 QMT 格式（`.SZ`/`.SH`/`.BJ`），后端会自动归一化为 QMT 格式
- `amount`：目标数量，`jukuan_order` 中正数为买入、负数为卖出
- `side`：方向，股票默认 `long`；期货可指定 `short`

## Token 安全机制

- 服务器主 Token 使用 `secrets.token_hex(32)` 随机生成，每次启动均不同
- 每个策略自动生成独立 Token（`secrets.token_hex(16)`），用于远程聚宽风格下单认证
- 策略 Token 可在「配置」tab 的策略列表中查看和复制
- `/api/jukuan_order*` 同时支持主 Token 和策略 Token
- 前端通过 Session Storage 存储 Token（页面刷新不丢失，关闭标签页即清除）
- `/api/server-info` 不再返回 Token，仅在 `/api/start-server` 响应中返回一次
- `/api/stop-server` 需要 X-Token 鉴权
- 页面加载时若服务器在运行但无可用的 Token，需手动输入 Token 连接

## 运行测试

```bash
pytest tests/ -v
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_HOST` | `0.0.0.0` | 服务器地址 |
| `SERVER_PORT` | `8000` | 服务器端口 |
| `MINI_QMT_PATH` | `` | miniQMT 路径 |
| `ACCOUNT_ID` | `` | 券商账户ID |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `WECHAT_WEBHOOK_URL` | `` | 企业微信通知 |
| `PERSISTENCE_MODE` | `sqlite` | 数据持久化模式：sqlite / memory |
| `DATABASE_URL` | `sqlite:///./data/qmt_live_assistant.db` | SQLAlchemy 数据库 URL |


