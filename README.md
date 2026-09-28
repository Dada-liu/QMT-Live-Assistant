➕V 一起探讨：hotpotdaxia

# QMT Live Assistant

基于 Python 服务器 + 原生 HTML 前端的 miniQMT 量化交易助手：接收聚宽等远程策略服务器的下单信号，经策略级资金/持仓校验后转发 QMT，并提供订单、持仓、信号的全链路监控。UI 采用 Coinbase 设计风格。

## 如何使用
1. [QMT-Live-Assistant 使用指南](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/qmt-live-assistant-usage/content.md)
2. [聚宽如何发送信号给 QMT-Live-Assistant](https://github.com/Dada-liu/QMT-Live-Assistant/blob/main/docs/jq-send-signal-to-qmt/content.md)

## 功能特性

**交易与下单**
- 可转债支持：策略种类可选「股票 / 可转债」（默认股票）；可转债委托单位为"张"、10 张/手（沿用 QMT `order_stock` 同一接口），行情（最新价/开盘价/前收盘/名称）与股票同链路直接可用；聚宽四接口、通用下单、手动下单、失败重发、挂起重试全链路按券种取整与校验；沪（110/111/113/118/132）、深（123/127/128/117）代码段自动识别；**策略种类与证券代码券种强校验**——股票策略下转债代码、转债策略下股票代码均拒绝下单；**可转债策略的市价单下单方式固定为"最新价"**（QMT 限制），前端切换策略种类时自动锁定，后端创建/更新接口同步校验
- 委托价 tick 对齐：所有限价委托价在下单汇聚点 `_submit_order` 统一按最小变动价位四舍五入对齐（股票 0.01 元、可转债 0.001 元；期货各品种 tick 不一，暂跳过），杜绝持仓均价（avg_cost 4 位小数）、市值/数量除法价等非 tick 价格被交易所拒单；对齐日志记录原始价 → 对齐价，接口返回与订单记录均为对齐后的实际委托价；前端手动下单与失败重发的价格校验同步按券种放宽（可转债支持 3 位小数）
- 聚宽风格下单：`/api/jukuan_order*` 四个接口（按数量/目标仓位/按金额/目标市值），仅接受策略 Token，自动关联策略并更新持仓；**统一按策略配置的默认市价方式提交 QMT（委托价 0）**
- 通用下单：`/api/order`（策略 Token），支持 `direction`、`quantity`、`price`、`price_type`、`order_type`、`source_platform`、`notify_source`、`source_platform_webhook` 等完整业务参数，适用于聚宽、果仁等任意外部信号源
- 策略信息查询：`/api/strategy_info`（策略 Token），外部服务可获取本策略的基本信息与资金汇总（分配资金/可用资金/总资产/当日盈亏），用于下单前的资金自查
- 手动下单：展开策略持仓明细即可点击买入/卖出，弹窗中选证券（买入自由输入、卖出从持仓选择）、数量（按券种整手步进：股票 100 股、可转债 10 张）、价格（市价/限价），复用策略级校验与冻结链路
- 策略级校验：卖出不超可用持仓；**所有买入路径均校验可用资金**（市价单按最新价估算成本）；超资处理可按策略配置——默认"放弃本次下单"，也可选"按最大可买数量下单"；**调仓场景可开启"资金不足时挂起等待卖出成交"**，同一策略存在在途卖单时买单因资金不足被拒绝将挂起，卖单部分/全部成交后自动重试买入；若卖出回款后仍不足一手则继续等待，不会误标失败（默认 30 分钟过期）；挂起重试下单会保留原始请求的 `notify_source` / `source_platform_webhook` / `source_platform`，订单终态仍正常回调源平台
- 源平台状态通知：下单时传入 `notify_source=true` 与 `source_platform_webhook`，订单成交/失败/撤销后服务端主动向该 webhook POST 结构化状态信息
- 订单主动管理：每日 09:30 开盘自动轮询刷新订单状态；待成交/部分成交订单可手动撤销；失败订单可在弹窗中修改价格与数量（支持市价/限价切换）后重发；部分成交时按 QMT 累计成交量更新，避免多次回调/轮询导致成交数量被重复累加

**策略管理**
- 多策略独立管理：各自分配资金、跟踪持仓与盈亏、独立 Token 认证
- 策略概览卡片：可用资金/总资产/当日盈亏/冻结资金，点击展开持仓明细，订单数可跳转订单列表并自动筛选
- 买入即冻结资金，成交转持仓、失败自动解冻，总资产展示不受未成交单影响

**监控与数据**
- 账户仪表板：可用资金/持仓市值/总资产/当日盈亏四卡片，点击可展开账户持仓明细
- 订单监控：按日期/策略/状态筛选；实时订单时间列展示完整年/月/日 时:分:秒，跨天订单可直接区分日期；价格列展示委托价（市价单显示"市价"）；信号日志"股票"列展示 股票名(代码)（查询时实时补充名称，历史日志同样生效，名称缺失时只显示代码），默认展示异常信号（含 max_buyable 封顶的部分下单），状态列错误信息以【报错时间】前缀标注报错发生时刻（精确到挂起超时等延迟报错场景，历史数据回退用接收时间），超出打点省略、hover 通过 tooltip 展示完整内容，便于排查问题
- Bark 手机推送：配置页绑定 iOS Bark Key 后，订单发起/成交/失败/超时未成交（分钟数可配，每笔仅提醒一次）自动推送到手机；失败与超时未成交为 critical 级别（静音/勿扰也提醒），失败带铃声；可按策略单独关闭推送
- 盈亏分析：交易时段（工作日 09:00–15:35）每 60 秒自动采集账户与启用策略的资产快照（总资产/可用资金/持仓市值/当日盈亏），按分钟落库 `asset_snapshots` 表；`GET /api/pnl/overview` 提供日/月/年收益曲线、每日收益（日历热力图数据）、月/年聚合收益（月视图返回当年各月 `monthly_returns`、年视图返回所有年份 `yearly_returns`，pnl 为日盈亏求和、收益率为日收益率连乘复合）与汇总指标（最新总资产/当日盈亏/累计收益率/区间收益率，月/年收益率由日收益率复合）；注意：出入金会直接影响总资产从而扭曲收益率（未做时间加权调整），且需先执行 `alembic upgrade head` 创建快照表；快照采集依赖的昨收/开盘价按日缓存、股票名称永久缓存，避免每分钟重复下载行情（Windows 真实 QMT 下 `download_history_data2` 可能耗时数十秒）；采集本身带防重入锁，上一轮未跑完直接跳过本轮
- 数据持久化：策略、持仓、订单、信号日志、应用设置（Bark 配置）默认落库 SQLite，重启不丢失

**连接与安全**
- QMT 连接看门狗：断线自动检测、指数退避重连，连接状态实时同步到页面
- 主 Token + 策略 Token 双层认证；跨终端可手动输入主 Token 连接
- 亮/暗双主题切换

**UI 交互**
- 全局 Confirm 弹窗组件（`frontend/js/confirm.js`）：Promise 风格 API，替代浏览器原生 `confirm()`，支持标题、消息、按钮文案自定义与危险/警告/信息视觉类型；已应用于「删除策略」「停止服务器」等关键操作

## 技术栈

- **后端**: Python 3.10+ / FastAPI / uvicorn / xtquant SDK / SQLAlchemy 2.0 / Alembic / SQLite
- **前端**: 原生 HTML + CSS + JS（ES Module，无框架无构建）

## 快速开始

前提：已安装 Python 环境与 QMT。`xtquant` SDK 仅 Windows 可用，macOS/Linux 自动使用 mock 实现。

```bash
pip install -r requirements.txt
alembic upgrade head   # 初始化 SQLite，数据文件位于 ./data/qmt_live_assistant.db
```

### 运行模式

```bash
# 仅启动管理界面与 API，浏览器中配置并启动服务
python -m backend.main --port 8000

# 无界面直接启动，控制台打印 Token
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini"
```

浏览器打开 `http://localhost:8000`，填写账户 ID 与 QMT 路径，点击「启动服务器」。

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

1. **创建策略**：名称、**策略种类**（股票/可转债，默认股票）与分配金额必填，可选配置"策略可用资金不足时"的处理方式（默认放弃本次下单，可选按最大可买数量下单）、"资金不足时挂起等待卖出成交（调仓场景）"开关，以及从账户现有持仓分配数量；创建后自动生成独立策略 Token；「管理策略」列表与「各策略资产」卡片的策略名旁展示种类标签
2. **下单关联**：远程策略用策略 Token 调 `/api/jukuan_order*`，订单自动关联到该策略；target/value 类接口按策略自身持仓与可用资金计算委托数量；调仓场景同时发出卖单+买单时，买单可因资金不足被挂起，等待同策略卖单成交后自动重试
3. **持仓与盈亏**：持仓仅持久化代码/名称/数量/成本价（QMT 格式），现价、市值、当日盈亏在请求时实时计算；每日首次刷新自动跨日合并（今日买入 → 昨日持仓，以昨收价为新成本基准）
4. **冻结与解冻**：买入下单即冻结资金（市价单按最新价估算），成交转持仓、失败/撤单自动解冻；接口返回的 `total_asset` 含冻结资金，`frozen_cash` 单独展示
5. **持仓/资金校验**：按策略级（而非账户整体）校验——卖出不超可用持仓；所有买入路径（按数量/目标仓位/按金额/目标市值/失败重发/手动下单）成本不超可用资金。超资时按策略的"策略可用资金不足时"配置处理：**放弃本次下单**（`reject`，默认）直接拒单报错；**按最大可买数量下单**（`max_buyable`）将买入数量封顶到可用资金可负担的最大整手数，不足一手则取消本次下单；若策略开启"资金不足时挂起等待卖出成交"且同一策略存在在途卖单（pending/partial），则买单会被挂起，卖单每笔成交后按增量回款入账，并在 5 秒轮询时自动重试买入，超时（默认 30 分钟）未成交标记失败并 Bark 通知；触发封顶、取消或挂起的信号会在信号日志中记为异常，`error_msg` 注明详情

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
| POST | `/api/strategies/{id}/order` | 手动下单：body `{"stock_code","direction":"buy\|sell","quantity","price","notify_source?","source_platform_webhook?","source_platform?"}`，price=0 为市价；买入须整手（股票 100 股、可转债 10 张）、卖出不超可用持仓、禁用策略返回 400 |

### 交易 API

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/test-connection` | 主 Token | 测试连接，返回资产数据 |
| GET | `/api/account-asset` | 主 Token | 账户资产 |
| GET | `/api/account-positions` | 主 Token | 账户持仓明细 |
| GET | `/api/orders` | 主 Token | 订单历史（`?status=&strategy_name=&start_date=&end_date=`），含 `retried_as_order_id` 重发链路字段 |
| POST | `/api/orders/{order_id}/cancel` | 主 Token | 撤销待成交/部分成交订单，标记 failed 并回滚策略持仓 |
| POST | `/api/orders/{order_id}/resend` | 主 Token | 重发失败订单（限 failed 且未重发过）；可选请求体 `{"quantity": int, "price": float}` 覆盖原参数（price=0 为市价），买入数量须为整手（股票 100 股、可转债 10 张） |
| GET | `/api/signal-logs` | 主 Token | 信号日志（`?status=&strategy_name=&start_date=&end_date=`） |
| GET | `/api/pnl/overview` | 主 Token | 盈亏分析（`?scope=account\|strategy&strategy_id=&period=day\|month\|year&date=YYYY-MM-DD`），返回 `summary`（total_asset/today_pnl/cum_return/period_return）、`curve`（day 为分钟点、month/year 为每日点）、`daily_returns`（day/month 返回当月、year 返回当年每日收益）、`monthly_returns`（仅 period=month，当年各月聚合，否则 null）、`yearly_returns`（仅 period=year，所有年份聚合，否则 null） |
| POST | `/api/convert/jq-to-qmt` | 主 Token | 聚宽→QMT 转换 |
| POST | `/api/convert/qmt-to-jq` | 主 Token | QMT→聚宽 转换 |
| POST | `/api/jukuan_order` | 策略 Token | 聚宽风格按数量下单；资金不足被挂起时返回 `deferred: true` |
| POST | `/api/jukuan_order_target` | 策略 Token | 聚宽风格目标持仓下单；重试时按当时持仓重新计算 delta |
| POST | `/api/jukuan_order_value` | 策略 Token | 聚宽风格按金额下单；资金不足被挂起时返回 `deferred: true` |
| POST | `/api/jukuan_order_target_value` | 策略 Token | 聚宽风格目标市值下单；重试时按当时持仓重新计算 delta |
| POST | `/api/order` | 策略 Token | 通用下单接口，参数最全，支持 `notify_source` / `source_platform_webhook` / `source_platform`；资金不足被挂起时返回 `deferred: true` |
| GET | `/api/strategy_info` | 策略 Token | 查询本策略基本信息与资金汇总（`security_type` / `allocated_funds` / `available_cash` / `total_asset` / `daily_pnl`），QMT 断开时返回 503 |

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

### Bark 推送配置

配置页可编辑的全局推送设置（主 Token），持久化到 SQLite `app_settings` 表：

- `GET /api/bark-config` — 读取配置
- `PUT /api/bark-config` — 保存配置
- `POST /api/bark-config/test` — 发送测试推送验证绑定（可用请求体中未保存的值先试）

```json
{
  "enabled": true,
  "device_key": "Bark App 中的设备 Key",
  "server_url": "https://api.day.app",
  "stale_minutes": 5
}
```

- 触发事件：订单发起、订单成交（普通级别）；订单失败（critical + alarm 铃声）、超过 `stale_minutes` 未成交（critical，每笔订单仅提醒一次）
- 策略编辑弹窗可单独关闭某个策略的推送（`bark_notify_enabled`，默认开启）；无策略订单只看全局开关
- 推送在 daemon 线程中异步发出，失败仅记录日志，不影响订单状态机

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

- `security`：证券代码，聚宽格式（`.XSHE`/`.XSHG`/`.XBJ`）、QMT 格式（`.SZ`/`.SH`/`.BJ`）或纯 6 位数字均可，后端自动归一化为 QMT 格式（纯数字按代码段补全市场后缀，含可转债精确分流：沪 110/111/113/118/132、深 123/127/128/117）
- `amount`：目标数量，正数买入、负数卖出
- `side`：股票默认 `long`；期货可指定 `short`
- `notify_source` / `source_platform_webhook` / `source_platform`：可选，开启源平台状态通知

> **价格行为**：四个 `/api/jukuan_order*` 接口统一按策略 `default_market_price_type` 提交市价委托（默认最新价），请求体不再接受 `price` 字段；`jukuan_order_value` / `jukuan_order_target_value` 仅在内部用行情/持仓价换算目标数量，实际委托仍为市价单。

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
| `SOURCE_PLATFORM_WEBHOOKS` | `{}` | 源平台 webhook 映射，JSON 字符串，如 `{"joinquant":"https://...","guoren":"https://..."}` |
| `PENDING_BUY_EXPIRE_MINUTES` | `30` | 调仓场景挂起买单的超时时间（分钟），超时后标记失败并通知 |
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
│   ├── logger.py            # 日志系统（控制台 + 按日轮转）
│   ├── constants.py         # 常量定义
│   ├── qmt_xtconstant.py    # QMT 常量映射
│   ├── window.py / tray.py  # ~~桌面窗口 / 系统托盘（已移除）~~
│   └── mock_xtquant/        # 非 Windows 平台的 mock
├── frontend/
│   ├── index.html           # 单页应用
│   ├── styles.css           # Coinbase 风格设计系统
│   └── js/                  # app / state / api / ui / config-panel
│                            # monitor / dashboard / strategy / docs / toast / security-utils
├── config/settings.py       # 环境变量配置
├── docs/                    # 使用文档（界面内可浏览）
├── product-doc/             # 产品与设计文档
├── tests/                   # pytest（含 repositories/ 与 jukuan_server/）
└── pytest.ini
```

## 运行测试

```bash
pytest tests/ -v
```

## 数据库迁移（Alembic）

表结构变更由 Alembic 统一管理（SQLAlchemy 2.0 + SQLite），迁移脚本位于 `backend/db/migrations/versions/`，数据文件为 `./data/qmt_live_assistant.db`。**应用启动时不会自动建表/迁移**，拉取包含新迁移的代码后需手动执行：

```bash
alembic upgrade head   # 迁移到最新版本
alembic current        # 查看当前版本
alembic history        # 查看完整迁移链
```

### 新增字段时的旧数据迁移流程

以「strategies 表新增 `security_type` 列」为例（对应迁移 `b5c1d8f2a3e4`）：

1. **修改数据库模型**：在 `backend/db/models/` 对应模型中添加列定义；
2. **编写迁移脚本**：`alembic revision -m "add security_type to strategies"` 生成骨架。**项目约定新列一律 `nullable=True`**，不要求存量行立刻有值：

   ```python
   def upgrade() -> None:
       # 存量数据为 NULL，读取时归一为 stock
       op.add_column('strategies', sa.Column('security_type', sa.String(length=32), nullable=True))

   def downgrade() -> None:
       op.drop_column('strategies', 'security_type')
   ```

3. **存量数据处理**（二选一）：
   - **读取归一**（推荐，项目惯例）：新列保持 NULL，Repository/领域模型读取时把 NULL 视作默认值——如 `security_type` NULL 归一为 `stock`、`insufficient_funds_policy` NULL 归一为 `reject`。零回填风险，可随时回滚；
   - **迁移回填**：确需把默认值落库时，在 `upgrade()` 中追加 UPDATE：
     ```python
     op.execute("UPDATE strategies SET security_type = 'stock' WHERE security_type IS NULL")
     ```
4. **同步改动**：领域模型（`backend/models/`）、Repository 映射、相关 API 与前端；
5. **执行迁移**：先备份 `./data/qmt_live_assistant.db`，再执行 `alembic upgrade head`；
6. **回归验证**：`pytest tests/ -v`。仓储层测试用 `Base.metadata.create_all` 建内存库，重点覆盖 NULL 存量数据的归一读取逻辑。

### 注意事项

- **回滚**：`alembic downgrade -1` 回退一步；回滚会删除新增列（连同回填的数据），操作前务必备份数据文件；
- **`downgrade()` 必须实现**：每个迁移脚本都要可回滚，与现有迁移保持一致；
- **SQLite 限制**：`ADD COLUMN` 直接支持，`DROP COLUMN` 需要 SQLite ≥ 3.35；**修改列类型或给已有列增删约束**需用 `batch_alter_table`（重建表）：

  ```python
  with op.batch_alter_table('orders') as batch_op:
      batch_op.alter_column('price', type_=sa.Float(), nullable=False)
  ```

- **迁移链**：脚本通过 `down_revision` 串联，多人协作产生多个 head 时用 `alembic merge heads` 合并。
