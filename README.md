➕V 一起探讨：hotpotdaxia

# QMT Live Assistant

基于 Python 服务器 + 原生 HTML 前端的 miniQMT 量化交易助手：接收聚宽等远程策略服务器的下单信号，经策略级资金/持仓校验后转发 QMT，并提供订单、持仓、信号的全链路监控。UI 采用 Coinbase 设计风格。

## 如何使用
1. [QMT-Live-Assistant 使用指南](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/qmt-live-assistant-usage/content.md)
2. [聚宽如何发送信号给 QMT-Live-Assistant](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/jq-send-signal-to-qmt/content.md)

## 功能特性

**交易与下单**
- 聚宽风格下单：`/api/jukuan_order*` 四个接口（按数量/目标仓位/按金额/目标市值），仅接受策略 Token，自动关联策略并更新持仓；无持仓时自动从行情获取最新价
- 通用下单：`/api/order`（策略 Token），支持 `direction`、`quantity`、`price`、`price_type`、`order_type`、`source_platform`、`notify_source`、`source_platform_webhook` 等完整业务参数，适用于聚宽、果仁等任意外部信号源
- 手动下单：展开策略持仓明细即可点击买入/卖出，弹窗中选股票（买入自由输入、卖出从持仓选择）、数量（100 整数倍步进）、价格（市价/限价），复用策略级校验与冻结链路
- 策略级校验：卖出不超可用持仓；**所有买入路径均校验可用资金**（市价单按最新价估算成本）；超资处理可按策略配置——默认"放弃本次下单"，也可选"按最大可买数量下单"
- 源平台状态通知：下单时传入 `notify_source=true` 与 `source_platform_webhook`，订单成交/失败/撤销后服务端主动向该 webhook POST 结构化状态信息
- 订单主动管理：每日 09:30 开盘自动轮询刷新订单状态；待成交/部分成交订单可手动撤销；失败订单可在弹窗中修改价格与数量（支持市价/限价切换）后重发

**策略管理**
- 多策略独立管理：各自分配资金、跟踪持仓与盈亏、独立 Token 认证
- 策略概览卡片：可用资金/总资产/当日盈亏/冻结资金，点击展开持仓明细，订单数可跳转订单列表并自动筛选
- 买入即冻结资金，成交转持仓、失败自动解冻，总资产展示不受未成交单影响

**监控与数据**
- 账户仪表板：可用资金/持仓市值/总资产/当日盈亏四卡片，点击可展开账户持仓明细
- 订单监控：按日期/策略/状态筛选；信号日志默认展示异常信号（含 max_buyable 封顶的部分下单），便于排查问题
- 数据持久化：策略、持仓、订单、信号日志默认落库 SQLite，重启不丢失

**连接与安全**
- QMT 连接看门狗：断线自动检测、指数退避重连，连接状态实时同步到页面
- 主 Token + 策略 Token 双层认证；跨终端可手动输入主 Token 连接
- 亮/暗双主题切换

## 技术栈

- **后端**: Python 3.10+ / FastAPI / uvicorn / xtquant SDK / SQLAlchemy 2.0 / Alembic / SQLite
- **前端**: 原生 HTML + CSS + JS（ES Module，无框架无构建）
- **桌面壳**: pywebview（原生窗口）/ pystray（系统托盘）/ PyInstaller（打包 exe）

## 快速开始

前提：已安装 Python 环境与 QMT。`xtquant` SDK 仅 Windows 可用，macOS/Linux 自动使用 mock 实现。

```bash
pip install -r requirements.txt
alembic upgrade head   # 初始化 SQLite，数据文件位于 ./data/qmt_live_assistant.db
```

### 运行模式

| 命令 | 模式 | 说明 |
|------|------|------|
| `--window` | 桌面窗口（Windows 推荐） | WebView2 窗口，关闭最小化到系统托盘 |
| `--tray` | 桌面壳 | 系统托盘 + 自动打开浏览器 |
| `--port 8000` | 前端界面 | 仅管理界面，浏览器中配置并启动服务 |
| `--account … --qmt-path …` | CLI 服务 | 无界面直接启动，控制台打印 Token |

```bash
# 例：桌面窗口模式
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini" --window

# 前端界面模式
python -m backend.main --port 8000
```

前端界面模式下，浏览器打开 `http://localhost:8000`，填写账户 ID 与 QMT 路径，点击「启动服务器」。

### nginx 反向代理部署

项目已支持通过 nginx 反向代理访问，可部署在根路径或子路径下。

**根路径代理**（`https://example.com/` → `localhost:8000`）：

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**子路径代理**（`https://example.com/qmt/` → `localhost:8000`）：

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    location /qmt/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix /qmt;
    }
}
```

子路径代理需在后端启动时设置 `ROOT_PATH`：

**Linux / macOS：**

```bash
ROOT_PATH=/qmt python -m backend.main --port 8000
```

**Windows cmd：**

```cmd
set ROOT_PATH=/qmt
python -m backend.main --port 8000
```

**Windows PowerShell：**

```powershell
$env:ROOT_PATH="/qmt"
python -m backend.main --port 8000
```

或者将配置写入 `.env` 文件（推荐，跨平台通用）：

```bash
# 复制示例文件并编辑
cp .env.example .env
```

`.env` 示例内容：

```env
ROOT_PATH=/qmt
CORS_ALLOW_ORIGINS=https://example.com
```

应用启动时会自动读取 `.env` 中的环境变量，Windows 上无需再写 `set` / `$env` 命令。

前端静态资源通过 `./static/...` 相对路径引用，API 请求基于页面路径动态计算 base URL，部署时无需修改前端代码。生产环境建议显式配置 `CORS_ALLOW_ORIGINS`，不要使用 `*`。

## 策略管理

1. **创建策略**：名称与分配金额必填，可选配置"策略可用资金不足时"的处理方式（默认放弃本次下单，可选按最大可买数量下单）与从账户现有持仓分配数量；创建后自动生成独立策略 Token
2. **下单关联**：远程策略用策略 Token 调 `/api/jukuan_order*`，订单自动关联到该策略；target/value 类接口按策略自身持仓与可用资金计算委托数量
3. **持仓与盈亏**：持仓仅持久化代码/名称/数量/成本价（QMT 格式），现价、市值、当日盈亏在请求时实时计算；每日首次刷新自动跨日合并（今日买入 → 昨日持仓，以昨收价为新成本基准）
4. **冻结与解冻**：买入下单即冻结资金（市价单按最新价估算），成交转持仓、失败/撤单自动解冻；接口返回的 `total_asset` 含冻结资金，`frozen_cash` 单独展示
5. **持仓/资金校验**：按策略级（而非账户整体）校验——卖出不超可用持仓；所有买入路径（按数量/目标仓位/按金额/目标市值/失败重发/手动下单）成本不超可用资金。超资时按策略的"策略可用资金不足时"配置处理：**放弃本次下单**（`reject`，默认）直接拒单报错；**按最大可买数量下单**（`max_buyable`）将买入数量封顶到可用资金可负担的最大整手数，不足一手则取消本次下单；触发封顶或取消的信号会在信号日志中记为异常，`error_msg` 注明请求股数与实际下单股数（或取消原因）

## API 参考

### 管理 API

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/health` | 无 | 健康检查 |
| GET | `/api/server-info` | 无 | 服务器状态（不含 Token） |
| POST | `/api/start-server` | 无 | 启动服务器，返回 Token |
| POST | `/api/stop-server` | X-Token | 停止服务器 |

### 策略管理 API（主 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategies` | 列出所有策略及数据 |
| POST | `/api/strategies` | 创建策略，返回策略及 Token |
| PUT | `/api/strategies/{id}` | 编辑策略 |
| DELETE | `/api/strategies/{id}` | 删除策略 |
| POST | `/api/strategies/{id}/toggle` | 切换启用/禁用 |
| POST | `/api/strategies/refresh` | 从 QMT 刷新策略持仓行情 |
| POST | `/api/strategies/{id}/order` | 手动下单：body `{"stock_code","direction":"buy\|sell","quantity","price","notify_source?","source_platform_webhook?","source_platform?"}`，price=0 为市价；买入须整手、卖出不超可用持仓、禁用策略返回 400 |

### 交易 API

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/test-connection` | 主 Token | 测试连接，返回资产数据 |
| GET | `/api/account-asset` | 主 Token | 账户资产 |
| GET | `/api/account-positions` | 主 Token | 账户持仓明细 |
| GET | `/api/orders` | 主 Token | 订单历史（`?status=&strategy_name=&start_date=&end_date=`），含 `retried_as_order_id` 重发链路字段 |
| POST | `/api/orders/{order_id}/cancel` | 主 Token | 撤销待成交/部分成交订单，标记 failed 并回滚策略持仓 |
| POST | `/api/orders/{order_id}/resend` | 主 Token | 重发失败订单（限 failed 且未重发过）；可选请求体 `{"quantity": int, "price": float}` 覆盖原参数（price=0 为市价），买入数量须为 100 的整数倍 |
| GET | `/api/signal-logs` | 主 Token | 信号日志（`?status=&strategy_name=&start_date=&end_date=`） |
| POST | `/api/convert/jq-to-qmt` | 主 Token | 聚宽→QMT 转换 |
| POST | `/api/convert/qmt-to-jq` | 主 Token | QMT→聚宽 转换 |
| POST | `/api/jukuan_order` | 策略 Token | 聚宽风格按数量下单 |
| POST | `/api/jukuan_order_target` | 策略 Token | 聚宽风格目标持仓下单 |
| POST | `/api/jukuan_order_value` | 策略 Token | 聚宽风格按金额下单 |
| POST | `/api/jukuan_order_target_value` | 策略 Token | 聚宽风格目标市值下单 |
| POST | `/api/order` | 策略 Token | 通用下单接口，参数最全，支持 `notify_source` / `source_platform_webhook` / `source_platform` |

### 源平台状态通知

外部系统下单时可在请求体中传入：

```json
{
  "security": "000001.XSHE",
  "direction": "buy",
  "quantity": 100,
  "price": 12.5,
  "notify_source": true,
  "source_platform_webhook": "https://your-server.com/callback",
  "source_platform": "joinquant"
}
```

当订单进入 **filled / failed** 终态时，服务端会以非阻塞方式向 `source_platform_webhook` POST：

```json
{
  "event": "order_state_changed",
  "order_id": "100001",
  "status": "filled",
  "source_platform": "joinquant",
  "stock_code": "000001.SZ",
  "jq_code": "000001.XSHE",
  "direction": "buy",
  "quantity": 100,
  "filled_quantity": 100,
  "filled_price": 12.5,
  "filled_amount": 1250.0,
  "error_msg": null,
  "timestamp": "2026-07-23T12:00:00+00:00"
}
```

- `notify_source` 默认为 `false`，不传则不触发通知
- `source_platform_webhook` 为空时，会尝试从环境变量 `SOURCE_PLATFORM_WEBHOOKS` 按 `source_platform` 查找对应 URL
- 通知失败仅记录日志，不影响订单状态机和策略持仓修正

### 动态端点（自动生成）

以下端点由 `QMTServer` 根据底层 trader 方法自动反射生成，路径中的方法名与 xtquant SDK 保持一致：

- `POST /api/order_stock` — 下单
- `POST /api/cancel_order_stock` — 撤单（对应 xtquant `cancel_order_stock`）
- `POST /api/query_stock_asset` — 查询资产
- `POST /api/query_stock_orders` — 查询委托
- `POST /api/query_stock_trades` — 查询成交
- `POST /api/query_stock_positions` — 查询持仓

> 业务上更推荐通过业务端点下单/撤单，例如 `POST /api/orders/{order_id}/cancel`。

### 错误处理

所有与 QMT 的同步交互（下单、撤单、查询）统一通过 `backend/utils.py` 的 `qmt_call` 封装：

- `order_stock` 返回 `-1`、
- `cancel_order_stock` 返回 `-1`、
- `query_*` 返回 `None`

均会被视为失败，服务端会记录包含方法名、调用上下文的错误日志，并返回 HTTP 500。`on_order_error` / `on_cancel_error` 回调也会结构化记录 `error_id`、`error_msg` 等字段。

### 聚宽下单格式

远程策略服务器**必须使用策略 Token** 调用 `/api/jukuan_order`（主 Token 调用返回 403）：

```json
{
  "security": "000001.XSHE",
  "amount": 100,
  "side": "long",
  "notify_source": true,
  "source_platform_webhook": "https://your-server.com/callback",
  "source_platform": "joinquant"
}
```

请求头：`X-Token: <策略Token>`

- `security`：证券代码，聚宽格式（`.XSHE`/`.XSHG`/`.XBJ`）或 QMT 格式均可，后端自动归一化为 QMT 格式
- `amount`：目标数量，正数买入、负数卖出
- `side`：股票默认 `long`；期货可指定 `short`
- `notify_source` / `source_platform_webhook` / `source_platform`：可选，开启源平台状态通知

## Token 安全机制

- 主 Token 使用 `secrets.token_hex(32)` 随机生成，每次启动均不同，保护管理/查询类接口；仅在 `/api/start-server` 响应中返回一次
- 每个策略自动生成独立 Token（`secrets.token_hex(16)`），用于聚宽风格下单认证，可在「配置」tab 查看和复制
- 前端 Token 存 Session Storage（刷新不丢，关闭标签页即清除）；服务器运行中但无 Token 时，可手动输入 Token 连接
- QMT 断开期间交易/账户接口返回 503，前端展示重连横幅；连接状态通过页面顶部 Logo 圆点实时展示（绿=已连接，黄=重连中，灰=已断开，红=失败）

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_HOST` | `127.0.0.1` | 服务器地址 |
| `SERVER_PORT` | `8000` | 服务器端口 |
| `ROOT_PATH` | `` | FastAPI 子路径，如 `/qmt`，用于 nginx 子路径代理 |
| `BASE_URL` | `` | 外部访问 URL 前缀，如 `https://example.com/qmt` |
| `CORS_ALLOW_ORIGINS` | `*` | 允许的跨域来源，多个用逗号分隔；生产环境请配置具体域名 |
| `CORS_ALLOW_CREDENTIALS` | `false` | 是否允许跨域请求携带凭证；为 `true` 时 `CORS_ALLOW_ORIGINS` 不能为 `*` |
| `MINI_QMT_PATH` | `` | miniQMT 路径 |
| `ACCOUNT_ID` | `` | 券商账户ID |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `WECHAT_WEBHOOK_URL` | `` | 企业微信通知 |
| `SOURCE_PLATFORM_WEBHOOKS` | `{}` | 源平台 webhook 映射，JSON 字符串，如 `{"joinquant":"https://...","guoren":"https://..."}` |
| `PERSISTENCE_MODE` | `sqlite` | 数据持久化模式：sqlite / memory |
| `DATABASE_URL` | `sqlite:///./data/qmt_live_assistant.db` | SQLAlchemy 数据库 URL |

## 项目结构

```
QMT-live-assistant/
├── backend/
│   ├── main.py              # FastAPI 入口（CORS、静态文件、管理 API、CLI）
│   ├── server.py            # QMTServer 核心（全部交易/策略路由）
│   ├── qmt_client.py        # miniQMT 连接与回调转发
│   ├── connection_watchdog.py # QMT 连接看门狗（断线重连）
│   ├── order_tracker.py     # 订单状态跟踪与撤销
│   ├── strategy_manager.py  # 策略管理器（CRUD、冻结/回滚/对账）
│   ├── jukuan_orders.py     # 聚宽风格下单
│   ├── source_platform_notifier.py # 源平台订单状态通知
│   ├── models/              # 领域模型（strategy.py / order.py）
│   ├── db/                  # 数据库层（models / repositories / migrations）
│   ├── utils.py             # 工具函数（代码转换、行情获取、时间工具）
│   ├── logger.py            # 日志系统（控制台 + 按日轮转 + 企业微信）
│   ├── constants.py         # 常量定义
│   ├── qmt_xtconstant.py    # QMT 常量映射
│   ├── window.py / tray.py  # 桌面窗口 / 系统托盘
│   └── mock_xtquant/        # 非 Windows 平台的 mock
├── frontend/
│   ├── index.html           # 单页应用
│   ├── styles.css           # Coinbase 风格设计系统
│   └── js/                  # app / state / api / ui / config-panel
│                            # monitor / dashboard / strategy / docs / toast
├── config/settings.py       # 环境变量配置
├── docs/                    # 使用文档（界面内可浏览）
├── product-doc/             # 产品与设计文档
├── tests/                   # pytest（含 repositories/ 与 jukuan_server/）
├── pyinstaller.spec         # exe 打包配置
└── pytest.ini
```

## 运行测试

```bash
pytest tests/ -v
```
