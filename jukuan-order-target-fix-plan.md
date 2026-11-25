# jukuan_order_target 修复详细方案（修订版）

> 基于 `/Users/yuliu/.claude/plans/jukuan-order-target-federated-kitten.md` 的检查结论制定，
> 并按评审意见修订（修订要点：修改项 2 简化、修改项 3/5 异常分级、修改项 6 保留透传字段、
> 修改项 1 加锁清单补全与定性）。

## 总体原则

1. 保持项目现有架构不变（StrategyManager、Repository、OrderTracker、QMTServer 等层级关系不变）。
2. 不修改端点 URL 和接口返回字段，仅调整内部行为与校验。
3. 所有改动配套新增/更新测试，保证 `pytest tests/ -q` 全绿。
4. 修改后同步更新 `README.md` 与 `product-doc/IMPLEMENTATION_PLAN.md` 中关于聚宽下单价格行为的描述，
   并顺带检查 `docs/jq-send-signal-to-qmt/` 是否描述了旧的限价/成本价行为。

---

## 修改项 1：乐观冻结原子化（P0）

### 问题
`apply_optimistic_position` / `rollback_position` / `reconcile_position` / `settle_partial_sell`
是"repo.get_by_id → 计算 → repo.save"两段式（`backend/strategy_manager.py`），
`@synchronized` 只覆盖单次 repo 调用，16 线程的 `run_blocking` 池
（`backend/utils.py:537-538`）并发下可超扣资金/重复调仓。

### 修改文件
- `backend/strategy_manager.py`
- `backend/db/base.py`（已存在 `db_lock`，无需新增）

### 具体修改

#### 1.1 在 `backend/strategy_manager.py` 顶部导入 `db_lock`
```python
from backend.db.base import db_lock
```

#### 1.2 给以下公共入口方法整体加锁
用上下文管理器包裹方法体内的"读策略 → 计算 → 持久化"全流程：

```python
def apply_optimistic_position(self, strategy_id: str, stock_code: str,
                              direction: str, quantity: int, price: float):
    with db_lock:
        # 原方法体不变
        ...
```

加锁清单（只锁公共入口方法）：
- `apply_optimistic_position`
- `rollback_position`
- `reconcile_position`（内部调用 `rollback_position`，RLock 可重入，无死锁）
- `settle_partial_sell`
- `update_position`（同样的读-改-写结构；当前 server/order_tracker 无直接调用，
  接近死代码，但它是公共变更入口，加锁成本极低，一并加锁防未来调用方踩坑。
  若确认永久无调用方，也可选择删除而非加锁，实施时二选一并说明）
- `add_trading_record`（只追加 records、不碰资金持仓，加锁非必须，低频无害，顺带加上）

**不加锁的说明**：
- `_apply_actual_fill` / `_freeze_position` 是 `@staticmethod` 纯函数，
  锁由调用它们的公共入口持有，自身不加锁。
- `create` / `update` / `delete` / `toggle` / `_rollover_positions_if_needed`
  也是读-改-写，但均由管理端低频操作或每日首次查询触发，与下单链路并发冲突的
  实际风险极低，本期不加锁，作为已知限制记录。

> 注意：`db_lock` 是 `threading.RLock()`，`@synchronized` 的 repo 方法在同一把锁内，可重入，不会死锁。

### 测试
- 在 `tests/test_strategy_manager.py` 新增并发测试（可参考 `tests/repositories/test_db_lock.py`
  的写法，用 InMemory repo 直接调 StrategyManager 方法，无需起 server）：
  - 10 个线程同时对一个策略买入同一股票，初始可用资金仅够买 500 股，验证最终冻结总量不超过 500 股。
  - 10 个线程同时 `order_target(0)`，初始持仓 100 股，验证最终只卖出 100 股（其余请求因可用持仓不足被拒绝）。

---

## 修改项 2：jukuan_order* 系列统一改为市价单（P0，已简化）

### 问题
`_get_price` 优先返回策略 `avg_cost`（`backend/jukuan_orders.py:96-103`），
导致有持仓时 `order_target` 以成本价挂限价单，清仓/加仓可能永不成交。

### 修改文件
- `backend/jukuan_orders.py`
- `tests/test_jukuan_orders.py`（同步更新断言）

### 具体修改

#### 2.1 `jukuan_order` / `jukuan_order_target`：直接传 `price=0.0`，不再取价

这两个方法的数量不依赖价格，改市价后完全无需取价，直接：

```python
submit_result = self._submit_order(
    stock_code, order_type, quantity, price=0.0, strategy_id=strategy_id
)
```

`_submit_order` 现有逻辑已覆盖所需行为，**无需任何签名修改**：
- `price <= 0` 且未显式指定 `price_type` 时，自动落到策略配置的默认市价类型
  （`_get_strategy_market_price_type`，未配置回退 `LATEST_PRICE`）；
- 市价买入单自动调 `fetch_latest_prices_from_xtdata` 取最新价做冻结估算
  （`jukuan_orders.py:260-266`）。

#### 2.2 `jukuan_order_value` / `jukuan_order_target_value`：用 `_get_reference_price` 换算数量，委托仍传 `price=0.0`

市值→数量换算需要一个参考价，但该参考价只用于估算数量，不作为委托价：

```python
price = _get_reference_price(
    self.trader, self.account, stock_code,
    strategy_manager=self.strategy_manager, strategy_id=strategy_id,
)
target_qty = abs(value) / price
quantity = _round_down_to_lot(target_qty, stock_code)
# ...
submit_result = self._submit_order(
    stock_code, order_type, quantity, price=0.0, strategy_id=strategy_id
)
```

#### 2.3 用 `_get_reference_price` 替换 `_get_price`

新函数语义明确为"仅用于估算"，不再优先返回 avg_cost：

```python
def _get_reference_price(trader, account, stock_code: str,
                         strategy_manager=None, strategy_id: Optional[str] = None) -> float:
    """获取用于数量换算/成本估算的参考价格。

    优先账户持仓市值价，无持仓时取行情最新价；不返回 avg_cost（避免限价单挂成本价）。
    """
    info = _get_position_info(trader, account, stock_code)
    if info['price'] > 0:
        return info['price']

    price_map = fetch_latest_prices_from_xtdata([stock_code])
    price = price_map.get(stock_code, 0.0)
    if price > 0:
        return price

    raise ReferencePriceUnavailableError(
        f"无法获取 {stock_code} 的最新价格，请确保持仓中有该股票或行情接口可用"
    )
```

（`ReferencePriceUnavailableError` 的定义见修改项 3。）

`_get_price` 删除；若担心外部引用，可保留一个委托到 `_get_reference_price` 的别名，
实施时全局 grep 确认无引用后直接删除即可。

### 可观测行为变化（需在测试与文档中锁定）

1. 四个方法返回 dict 的 `price` 字段变为 `0.0`（市价单无委托价），
   `add_trading_record` 记录的委托价随之全为 0。**决策：接受为 0**，
   price=0 即表示市价委托；实际成交价由订单成交回报/对账链路体现，
   trading_records 回填实际成交价列为可选后续项，本期不做。
2. `jukuan_order` 卖出路径不再调 `_get_price`，"无持仓且无行情"时的报错从
   "无法获取最新价格"变为"策略可用持仓不足"——语义更准确，测试断言同步更新。
3. 提前返回分支核对：`jukuan_order_target` 的 `delta == 0` / 不足一手分支在取价之前，
   无影响；`jukuan_order_value` 取价失败依旧抛错（异常类型变为
   `ReferencePriceUnavailableError`，见修改项 3），行为不变但测试要锁定。

### 测试更新
- `TestJukuanOrder.test_buy` / `test_sell`：断言 `price_type == LATEST_PRICE`，`price == 0`。
- `TestJukuanOrderTarget.test_increase` / `test_decrease`：断言 `price_type == LATEST_PRICE`，`price == 0`。
- `TestJukuanOrderStrategyScoped.test_target_uses_strategy_quantity`：断言 `price_type == LATEST_PRICE`。
- 新增测试：有持仓时 order_target(0) 用市价卖出，不依赖 avg_cost。
- 新增测试：order_value 的数量换算使用 `_get_reference_price`（行情价），不使用 avg_cost。

---

## 修改项 3：市价买入行情缺失时拒绝下单（P1，瞬时异常分级）

### 问题
`freeze_price=0` 时资金校验被跳过，成交后 `available_cash` 可能变负。
但行情接口短暂不可用是**瞬时**错误，不能与参数校验类永久错误混为一谈，
否则挂起买单遇到行情抖动会被修改项 5 直接判死。

### 修改文件
- `backend/jukuan_orders.py`

### 具体修改

#### 3.1 新增专用异常（不继承 ValueError，供重试链路区分瞬时错误）

```python
class ReferencePriceUnavailableError(RuntimeError):
    """行情参考价不可用（瞬时错误）。

     deliberately 不继承 ValueError：挂起买单重试链路对 ValueError 做
    fail-fast（永久错误），而行情抖动应等待下一轮重试。
    继承 RuntimeError 使其向上传播到 process_all 的兜底捕获，
    挂起买单保持 waiting。
    """
```

（注释按项目风格精简，此处仅为说明意图。）

#### 3.2 `_submit_order` 现有 freeze 估算逻辑后增加硬校验

在现有市价买入取行情估算的代码（`jukuan_orders.py:260-266`）之后：

```python
    if (direction == 'buy'
            and (price <= 0 or is_market_price_type(final_price_type))
            and strategy_id and self.strategy_manager is not None):
        freeze_price = fetch_latest_prices_from_xtdata([stock_code]).get(stock_code, 0.0)
        if freeze_price <= 0:
            raise ReferencePriceUnavailableError(
                f"{stock_code} 市价买入无法获取行情参考价，无法估算冻结成本，订单取消"
            )
```

同时把 `_get_reference_price`（修改项 2.3）中的 `ValueError` 也改为抛
`ReferencePriceUnavailableError`。

### 测试
- mock `fetch_latest_prices_from_xtdata` 返回 `{}`，验证市价买入抛
  `ReferencePriceUnavailableError`，且不调用 QMT。

---

## 修改项 4：持仓查询失败不降级为"无持仓"（P1）

### 问题
`_get_position_info` 吞掉所有异常返回空持仓，`order_target` 可能基于错误持仓下单。

### 修改文件
- `backend/jukuan_orders.py`

### 具体修改

#### 4.1 修改 `_get_position_info`

删除 `try/except Exception: positions = []` 的静默降级，让 `qmt_call` 异常透明抛出：

```python
def _get_position_info(trader, account, stock_code: str) -> dict:
    """查询指定 QMT 代码在账户中的持仓信息。

    查询失败时异常直接向上抛（fail-fast），不降级为"无持仓"，
    避免基于错误持仓做出调仓决策。
    """
    positions = qmt_call(
        trader,
        "query_stock_positions",
        account,
        context={"stock_code": stock_code, "account_id": getattr(account, 'account_id', account)},
    )

    for pos in positions:
        pos_code = getattr(pos, 'stock_code', '')
        if pos_code != stock_code:
            continue
        volume = getattr(pos, 'volume', 0) or 0
        market_value = getattr(pos, 'market_value', 0.0) or 0.0
        if volume > 0 and market_value > 0:
            price = market_value / volume
        else:
            price = getattr(pos, 'open_price', 0.0) or 0.0
        return {
            'volume': volume,
            'price': price,
            'found': True,
        }

    return {'volume': 0, 'price': 0.0, 'found': False}
```

#### 4.2 影响面（需在测试与文档中锁定）

- "QMT 持仓查询失败但行情可用"的场景将整单失败——这是有意的 fail-fast，行为变更需明确。
- 无 strategy_id 的 `order_target` 走账户持仓查询，QMT 查询失败时同样整单失败。
- 实施时确认 `qmt_call`（`backend/utils.py:495`）是否已有重试/超时包装，
  避免"内部重试 + 外层挂起买单重试"双重放大延迟；如有则在方案落地时记录其实际行为。

### 测试
- mock `query_stock_positions` 抛异常，验证 `jukuan_order_target` 直接抛异常，不调用 `order_stock`。

---

## 修改项 5：挂起买单永久异常 fail-fast（P1，区分瞬时/永久）

### 问题
`pending_buy_manager._retry` 只捕获 `InsufficientFundsError`，`ValueError` 等永久异常会重试 30 分钟。

### 修改文件
- `backend/pending_buy_manager.py`

### 具体修改

在 `_retry` 中增加对 `ValueError` 的捕获：

```python
try:
    result = self._invoke(handler, pb)
except InsufficientFundsError:
    # 资金仍不足，等下一笔卖单回款
    return
except ValueError as e:
    # 券种校验失败、代码格式错误等永久错误，直接失败
    self._resolve(pb, PENDING_BUY_FAILED, str(e))
    return
```

注意事项：
- **except 顺序必须先 `InsufficientFundsError` 后 `ValueError`**——
  `InsufficientFundsError` 是 `ValueError` 的子类（`jukuan_orders.py:34`），写反会导致
  资金不足被误判为永久失败。
- **`ReferencePriceUnavailableError`（修改项 3）不捕获**：它继承 `RuntimeError`，
  会向上传播到 `process_all` 的 per-item 兜底捕获（记日志、继续处理下一单），
  挂起买单保持 `waiting` 等下一轮，行情恢复后自动重试——这正是瞬时错误的预期语义。

### 测试
- 在 `tests/repositories/test_pending_buy.py` 或 `tests/test_server.py` 新增测试：
  - mock `_invoke` 抛 `ValueError("券种校验失败")`，验证状态直接变为 `PENDING_BUY_FAILED`。
  - mock `_invoke` 抛 `ReferencePriceUnavailableError`，验证状态保持 `PENDING_BUY_WAITING`。

---

## 修改项 6：端点参数校验（P2，保留透传字段）

### 问题
`/api/jukuan_order_target` 等端点直接 `request.get`，非法输入导致 500。

### 修改文件
- `backend/server.py`
- `backend/models/order.py`（参考现有 Pydantic 模型风格）

### 具体修改

新增 Pydantic 模型。**必须显式声明源平台回调字段**——端点在 `server.py:964-966`
读取 `notify_source` / `source_platform_webhook` / `source_platform`，挂起买单重试路径
也从原始 payload 恢复这三个字段（`pending_buy_manager.py:163-165`）；
若模型漏声明，`model_dump()` 会静默丢弃它们，源平台终态回调失效：

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any

class _JukuanBaseRequest(BaseModel):
    security: str = Field(..., min_length=1, description="聚宽格式证券代码")
    side: Literal['long', 'short'] = 'long'
    # 源平台回调字段：端点与挂起买单重试链路依赖，必须透传，不可省略
    notify_source: bool = False
    source_platform_webhook: Optional[str] = None
    source_platform: Optional[str] = None

class JukuanOrderTargetRequest(_JukuanBaseRequest):
    amount: int = Field(..., ge=0, description="目标持仓数量")

class JukuanOrderRequest(_JukuanBaseRequest):
    amount: int = Field(..., description="正数买入，负数卖出")

class JukuanOrderValueRequest(_JukuanBaseRequest):
    value: float = Field(..., description="正数买入，负数卖出")

class JukuanOrderTargetValueRequest(_JukuanBaseRequest):
    value: float = Field(...)
```

端点改为接收模型：

```python
@app.post('/api/jukuan_order_target')
async def jukuan_order_target_endpoint(request: JukuanOrderTargetRequest,
                                       raw_request: Request,
                                       x_token: str = Header(...)):
    payload = request.model_dump()
    return await _jukuan_endpoint(payload, x_token, 'jukuan_order_target', raw_request)
```

实施时核对 `_jukuan_endpoint` 及其下游（含挂起买单 `defer` 的 payload 持久化）
实际读取的所有字段，确保模型字段全集覆盖；如有未声明的扩展字段，用
`model_config = ConfigDict(extra='allow')` 兜底并在注释中说明原因。

### 测试
- 传入 `amount="abc"` / 负数 amount / 缺失 security，验证返回 422。
- 传入完整字段（含 `notify_source` / `source_platform_webhook` / `source_platform`），
  验证 `_jukuan_endpoint` 收到的 payload 中这三个字段原样保留。

---

## 修改项 7：文档更新

### 修改文件
- `README.md`
- `product-doc/IMPLEMENTATION_PLAN.md`
- 检查 `docs/jq-send-signal-to-qmt/`

### 更新内容
- 在"交易与下单"特性中说明：`/api/jukuan_order*` 统一按策略配置的默认市价方式下单，不再以持仓成本价挂限价单；委托记录中 price=0 表示市价单。
- 删除或修正任何"限价/成本价"相关描述。
- 在 IMPLEMENTATION_PLAN.md 中补充：
  - 并发乐观冻结已加全局 RLock（含加锁范围与未加锁方法的理由）；
  - 市价买入行情缺失保护（瞬时异常 `ReferencePriceUnavailableError`）；
  - 持仓查询失败不下单（fail-fast）；
  - 挂起买单永久异常 fail-fast、瞬时异常保持等待的异常分级。

---

## 修改顺序与依赖

| 顺序 | 修改项 | 依赖 |
|---|---|---|
| 1 | 乐观冻结原子化 | 无 |
| 2 | jukuan_order* 改市价单（含 `_get_reference_price`） | 无，但与测试断言冲突需同步更新；异常类在项 3 定义，可先定义占位 |
| 3 | 市价买入行情缺失保护（`ReferencePriceUnavailableError`） | 依赖项 2 完成后更自然；异常类定义可提前到项 2 |
| 4 | 持仓查询失败不下单 | 无 |
| 5 | 挂起买单 ValueError fail-fast | 依赖项 3 的异常分级，测试需覆盖瞬时异常保持 waiting |
| 6 | 端点参数校验 | 无 |
| 7 | 文档更新 | 依赖项 2 完成后 |

实施提示：项 2 与项 3 强耦合（`_get_reference_price` 抛的就是项 3 的异常类），
建议在同一次改动中完成，先定义 `ReferencePriceUnavailableError`。

---

## 风险与回退

1. **改市价单风险**：若策略 `default_market_price_type` 配置不当（如极端市价类型），实际成交价可能与预期偏差大。建议默认保持 `LATEST_PRICE=5`。
2. **加锁风险**：全局 RLock 会串行化所有策略资金/持仓操作，16 线程池并发下吞吐量下降，但单次操作在内存+SQLite 为微秒级，影响可忽略。
3. **测试更新风险**：`tests/test_jukuan_orders.py` 中多处断言 `price_type == FIX_PRICE`，需批量替换为 `LATEST_PRICE`，否则测试会红。
4. **已知残余并发风险（本期不处理，如实记录）**：`order_target` 的 delta 计算（读当前持仓）在 handler 层，冻结在 StrategyManager 层；即使 StrategyManager 方法加锁，"读持仓 → 算 delta → 冻结"整体仍非原子。两个并发 `order_target(500)` 会各自算出 delta=500 并重复提交——买入方向由资金冻结兜底（第二笔报资金不足）、卖出方向由可用持仓兜底（第二笔抛异常），表现为异常而非幂等拒绝。
5. **未加锁的管理端方法**：`create` / `update` / `delete` / `toggle` / `_rollover_positions_if_needed` 同为读-改-写，因低频且与下单链路并发冲突风险极低，本期不加锁（见修改项 1）。
6. **行为变更**：委托记录 price=0（市价单）、卖出路径报错语义变化、持仓查询失败整单失败——均为有意变更，已在对应修改项中锁定测试。

---

## 验证清单

- [ ] `pytest tests/ -q` 全部通过
- [ ] 并发测试验证资金不透支、持仓不重复卖出
- [ ] 市价买入行情缺失测试抛 `ReferencePriceUnavailableError`
- [ ] 持仓查询失败测试抛异常
- [ ] 挂起买单 ValueError 测试直接 failed；`ReferencePriceUnavailableError` 测试保持 waiting
- [ ] 端点参数校验测试返回 422；源平台回调字段透传测试通过
- [ ] `python3 -m py_compile backend/main.py backend/jukuan_orders.py backend/strategy_manager.py backend/pending_buy_manager.py backend/server.py` 通过
- [ ] README.md / IMPLEMENTATION_PLAN.md 已更新，`docs/jq-send-signal-to-qmt/` 已检查
