# 下单方式总结

## 方式一：`POST /api/receive-signal`（主要方式）

**用途：** 接收外部策略引擎（聚宽、自定义脚本等）的交易信号，自动转换为 QMT 订单。

**Token：** 主 Token 或策略 Token（策略需处于启用状态）

**代码转换：** 自动将聚宽格式（`000001.XSHE`）转换为 QMT 格式（`000001.SZ`）

**价格模式：** 自动选择 — `price > 0` 时限价单（`FIX_PRICE = 11`），否则市价单（`LATEST_PRICE = 5`）

**策略记账：** 下单成功后自动更新策略持仓、可用资金、信号计数、交易记录

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `signal_id` | string | 是 | 唯一信号标识 |
| `stock_code` | string | 是 | 聚宽格式，如 `000001.XSHE` |
| `direction` | string | 是 | `"buy"` 或 `"sell"` |
| `quantity` | int | 是 | 股数 |
| `price` | float | 否 | 限价；省略/0 则市价 |
| `strategy_name` | string | 否 | 策略名称（策略 Token 自动填充） |
| `timestamp` | string | 否 | ISO 时间戳 |

**处理流程：**

```
外部 HTTP POST → Token 验证（策略匹配）→ 股票代码转换 → 方向映射（buy=23/sell=24）
→ 价格模式判断 → trader.order_stock() → 追加信号日志 → 更新策略持仓/资金/记录
```

**代码位置：**
- 路由：`backend/server.py:191-237`
- 核心逻辑：`backend/signal_handler.py:33-105`
- 代码转换：`backend/qmt_client.py:161-168`

---

## 方式二：聚宽风格下单 API（新增）

**用途：** 与聚宽原生 API 语义一一对应，聚宽用户可直接用熟悉的函数下单。

**Token：** 主 Token 或策略 Token（策略需处于启用状态）

**代码转换：** 自动将聚宽格式（`000001.XSHE`）转换为 QMT 格式（`000001.SZ`）

**价格模式：** 统一使用市价单（`LATEST_PRICE = 5`）

**策略记账：** 下单成功后自动更新策略信号计数和交易记录

**手数规则：** 股票 1 手 = 100 股，期货 1 手 = 1 张；不足 1 手时向下取整，取整后为 0 则不下单

### `POST /api/jukuan_order` — 按股/手数下单

正数买入，负数卖出。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `security` | string | 是 | 聚宽格式股票代码，如 `000001.XSHE` |
| `amount` | int | 是 | 正数买入，负数卖出 |
| `side` | string | 否 | 期货方向：`"long"`（默认）或 `"short"` |

```python
# 示例
jukuan_order('000001.XSHE', 100)              # 买入 100 股平安银行
jukuan_order('000001.XSHE', -100)             # 卖出 100 股平安银行
jukuan_order('000001.XSHE', 99)               # 不足一手 → order_id=null
jukuan_order('IF1901', 10, side='long')       # 开多 10 手 IF1901
jukuan_order('IF1901', -5, side='short')      # 平空 5 手 IF1901
```

### `POST /api/jukuan_order_target` — 调仓至目标股数

将持仓调整至目标数量，计算 delta = 目标 - 当前持仓。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `security` | string | 是 | 聚宽格式股票代码 |
| `amount` | int | 是 | 目标持仓数量 |
| `side` | string | 否 | 期货方向 |

```python
# 示例（假设当前持仓 500 股平安银行）
jukuan_order_target('000001.XSHE', 700)       # 买入 200 股（500→700）
jukuan_order_target('000001.XSHE', 200)       # 卖出 300 股（500→200）
jukuan_order_target('000001.XSHE', 500)       # 已满足 → order_id=null
jukuan_order_target('000001.XSHE', 0)         # 全部平仓
```

### `POST /api/jukuan_order_value` — 按价值下单

按金额下单，股数 = 金额 ÷ 当前价格，向下取整至一手。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `security` | string | 是 | 聚宽格式股票代码 |
| `value` | float | 是 | 正数买入，负数卖出（单位：元） |
| `side` | string | 否 | 期货方向 |

```python
# 示例（假设平安银行当前价格 10 元）
jukuan_order_value('000001.XSHE', 10000)      # 10000/10 = 1000 股买入
jukuan_order_value('000001.XSHE', 750)        # 750/10 = 75 → 取整 0 股，不下单
jukuan_order_value('000001.XSHE', -2000)      # 卖出 200 股
```

### `POST /api/jukuan_order_target_value` — 调仓至目标价值

将持仓市值调整至目标金额，计算 delta = 目标价值 - 当前市值。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `security` | string | 是 | 聚宽格式股票代码 |
| `value` | float | 是 | 目标市值（单位：元） |
| `side` | string | 否 | 期货方向 |

```python
# 示例（假设持仓 500 股，当前价格 10 元，市值 5000 元）
jukuan_order_target_value('000001.XSHE', 10000)  # 再买 500 股（5000→10000）
jukuan_order_target_value('000001.XSHE', 5000)   # 已满足 → order_id=null
jukuan_order_target_value('000001.XSHE', 0)      # 全部平仓
```

**代码位置：**
- 路由：`backend/server.py`（setup_routes 中聚宽下单 API 段）
- 核心逻辑：`backend/jukuan_orders.py`

---

## 方式三：动态 API `/api/{method_name}`（直接调用）

**用途：** 直接调用 QMT 交易者的原生方法，用于调试或手动操作。

**Token：** 仅主 Token（无策略 Token 支持）

**代码转换：** 无，需直接传入 QMT 格式代码

**策略记账：** 无

服务器启动时自动扫描 `XtQuantTrader` 的公开方法，为每个方法注册 `POST /api/{method_name}` 端点。排除的方法：`__init__`、`start`、`stop`、`connect`、`register_callback` 等。

**可用的下单相关端点：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /api/order_stock` | 下单 | 直接调用 QMT 下单接口 |
| `POST /api/cancel_order` | 撤单 | 撤销指定订单 |
| `POST /api/query_stock_orders` | 查委托 | 查询当日委托 |
| `POST /api/query_stock_trades` | 查成交 | 查询当日成交 |
| `POST /api/query_stock_positions` | 查持仓 | 查询当前持仓 |
| `POST /api/query_stock_asset` | 查资产 | 查询账户资金 |
| `POST /api/query_all_orders` | 查所有委托 | 查询所有委托记录 |
| `POST /api/query_all_trades` | 查所有成交 | 查询所有成交记录 |

**`POST /api/order_stock` 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `account` | StockAccount | 自动注入，无需传 |
| `stock_code` | string | QMT 格式，如 `000001.SZ` |
| `order_type` | int | 23=买入，24=卖出 |
| `order_volume` | int | 股数 |
| `price_type` | int | 5=市价，11=限价 |
| `price` | float | 价格（市价时传 0） |
| `strategy_name` | string | 策略名称标识 |
| `order_remark` | string | 备注 |

**代码位置：**
- 动态路由注册：`backend/server.py:86-128`
- QMT 连接：`backend/qmt_client.py:108-158`

---

## 方式四：QMT 回调（被动反馈）

不是下单方式，而是 QMT 对已提交订单的异步状态通知：

| 回调 | 说明 | 代码位置 |
|------|------|------|
| `on_stock_order` | 订单状态变更（已委托/已撤单） | `qmt_client.py:25-51` |
| `on_stock_trade` | 订单成交 | `qmt_client.py:53-71` |
| `on_order_error` | 委托失败 | `qmt_client.py:73-88` |
| `on_cancel_error` | 撤单失败 | `qmt_client.py:90-105` |
| `on_disconnected` | QMT 连接断开 | `qmt_client.py:16-23` |

所有回调事件会写入 `signal_log`，前端每 5 秒轮询 `GET /api/signals` 展示。

---

## 三种下单方式对比

| | `/api/receive-signal` | `/api/jukuan_*` | `/api/order_stock` |
|---|---|---|---|
| Token | 主 Token 或策略 Token | 主 Token 或策略 Token | 仅主 Token |
| 股票代码 | 自动聚宽→QMT 转换 | 自动聚宽→QMT 转换 | 需 QMT 格式 |
| 价格模式 | 自动选择（限价/市价） | 统一市价单 | 需手动指定 `price_type` |
| 策略记账 | 自动更新持仓/资金 | 自动更新信号计数/交易记录 | 无 |
| 信号日志 | 记录 | 记录 | 无 |
| 手数取整 | 无（直接传股数） | 自动向下取整到一手 | 无 |
| 适用场景 | 外部策略引擎通用信号 | 聚宽用户原生下单体验 | 调试/手动操作 |

---

## 前端

前端**不提供手动下单 UI**。前端功能为：
- 服务器配置与启停
- 账户资产仪表板（只读）
- 策略管理（CRUD、启用/禁用、Token 复制）
- 信号/订单/成交时间线监控（只读，5 秒轮询）
- 聚宽 ↔ QMT 代码转换工具
