# QMT Live Assistant

基于 Python 服务器 + 原生 HTML 前端的 miniQMT 量化交易助手。Python 服务器代码参考 `qka` 项目，UI 设计采用 Coinbase 网站的风格。

## 功能

- 连接 miniQMT 交易终端（迅投 XtQuant SDK）
- 启动/停止本地交易服务器
- 测试连接并获取账户资产（可用资金、持仓市值、总资产、当日盈亏）
- 接收远程策略服务器的交易信号，自动下单
- 实时信号监控面板
- 聚宽格式 ↔ QMT 格式代码转换
- 亮/暗双主题切换
- Token 认证保护所有 API 端点

## 技术栈

- **后端**: Python 3.10+ / FastAPI / uvicorn / xtquant SDK
- **前端**: 原生 HTML + CSS + JS（ES Module）
- **设计**: Coinbase 设计风格

## 项目结构

```
QMT-live-assistant/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── server.py            # QMTServer 核心
│   ├── qmt_client.py        # miniQMT 连接 + 代码转换
│   ├── signal_handler.py    # 远程信号接收
│   ├── utils.py             # 工具函数
│   ├── logger.py            # 日志系统
│   ├── constants.py         # 常量定义
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
│       ├── monitor.js       # 信号监控
│       └── dashboard.js     # 仪表板
├── config/
│   └── settings.py
├── tests/
│   ├── test_client.py
│   ├── test_server.py
│   └── test_signal_handler.py
├── requirements.txt
└── README.md
```

## 安装

前提：安装了 python 环境和 QMT

```bash
pip install -r requirements.txt
```

> **注意**: `xtquant` SDK 仅在 Windows 上可用。在 macOS/Linux 上，项目自动使用 mock 实现进行开发和测试。

## 运行

### 前端界面模式（推荐）

启动管理界面，通过浏览器配置和监控：

```bash
python -m backend.main --port 8000
```

浏览器打开 `http://localhost:8000`，填写账户ID和QMT路径，点击"启动服务器"。

### CLI 模式

跳过前端，直接启动交易服务器：

```bash
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端模拟\userdata_mini" --port 8000
```

启动后控制台会打印 Token，远程信号服务器使用此 Token 调用 API。

## API 参考

### 管理 API（仅前端模式）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/server-info` | 服务器状态 |
| POST | `/api/start-server` | 启动服务器 |
| POST | `/api/stop-server` | 停止服务器 |

### 交易 API（需要 X-Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/test-connection` | 测试连接，返回资产数据 |
| GET | `/api/server-status` | 交易服务器状态 |
| GET | `/api/account-asset` | 账户资产 |
| GET | `/api/signals` | 信号历史 |
| POST | `/api/convert/jq-to-qmt` | 聚宽→QMT 转换 |
| POST | `/api/convert/qmt-to-jq` | QMT→聚宽 转换 |
| POST | `/api/receive-signal` | 接收远程信号 |

### 动态端点（自动生成）

以下端点根据 XtQuantTrader 方法自动生成，所有端点需要 X-Token：

- `POST /api/order_stock` — 下单
- `POST /api/cancel_order` — 撤单
- `POST /api/query_stock_asset` — 查询资产
- `POST /api/query_stock_orders` — 查询委托
- `POST /api/query_stock_trades` — 查询成交
- `POST /api/query_stock_positions` — 查询持仓

### 信号格式

远程策略服务器发送信号到 `/api/receive-signal`：

```json
{
  "signal_id": "sig-20260528-001",
  "stock_code": "000001.XSHE",
  "direction": "buy",
  "quantity": 100,
  "price": 12.50,
  "order_type": "limit",
  "strategy_name": "momentum-v1"
}
```

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
