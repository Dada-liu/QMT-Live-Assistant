# Phase 3：认证安全升级计划

> 本文档依据 `reconstruction-doc/THINKING.md` 制定，目标是将当前简单的随机 Token 认证升级为更安全的方案：管理端使用 JWT Access/Refresh Token，策略远程下单使用可吊销、可过期的策略 Token。

---

## 一、目标与范围

### 1.1 核心目标

1. 引入 JWT Access Token + Refresh Token 机制，用于管理端认证。
2. 策略 Token 支持吊销、过期、轮换、最近使用时间记录。
3. 新增登录、Token 刷新、登出接口。
4. 管理类 API（策略管理、服务器启停、订单查询等）改用 JWT 认证。
5. 远程下单类 API（`/api/jukuan_order*`）继续使用策略 Token，但改为查询数据库验证有效性。
6. Token 泄露后可主动吊销，降低风险。

### 1.2 本次不做

- 多用户权限系统（RBAC）（可作为后续增强）
- OAuth / SSO 集成
- 单点登录（SSO）
- 前端 React 化改造中的认证 UI 细节（仅适配 JWT 刷新逻辑）

### 1.3 验收标准

- [ ] 新增 `/api/auth/login`、`/api/auth/refresh`、`/api/auth/logout` 接口。
- [ ] 管理接口使用 JWT 认证，无 JWT 或 JWT 过期返回 401。
- [ ] 策略 Token 存储在数据库，支持吊销/过期/轮换。
- [ ] 策略 Token 被吊销后，携带该 Token 的下单请求返回 401。
- [ ] Access Token 过期后可用 Refresh Token 换取新的 Access Token。
- [ ] Refresh Token 登出后被加入黑名单，无法再次使用。
- [ ] 前端自动处理 Access Token 过期刷新。
- [ ] 现有测试通过，新增认证相关测试覆盖核心路径。

---

## 二、现状分析

### 2.1 当前认证机制

`backend/server.py`：

```python
async def _verify_token(x_token: str = Header(...)):
    if _current_server is None:
        raise HTTPException(status_code=401, detail="服务器未运行")
    if x_token != _current_server.token:
        raise HTTPException(status_code=401, detail="无效的Token")
    return x_token

async def _verify_any_token(x_token: str = Header(...)):
    if _current_server is None:
        raise HTTPException(status_code=401, detail="服务器未运行")
    if x_token == _current_server.token:
        return x_token
    strategy = _current_server.strategy_manager.find_by_token(x_token)
    if strategy and strategy.enabled:
        return x_token
    raise HTTPException(status_code=401, detail="无效的Token")
```

`backend/strategy_manager.py`：

```python
class Strategy(BaseModel):
    token: str = Field(default_factory=lambda: secrets.token_hex(16))
```

### 2.2 当前问题

1. **服务器 Token 无过期时间**：一旦泄露，永久有效，只能重启服务换 Token。
2. **策略 Token 无吊销机制**：泄露后无法单独吊销某个策略 Token。
3. **无 Refresh Token**：Access Token 过期后需要重新登录（如果未来引入登录）。
4. **settings.py 中 SECRET_KEY 未使用**：已有配置但未接入认证。
5. **认证与业务代码耦合**：`_verify_token` 直接依赖全局 `_current_server`。

### 2.3 与 Phase 1/2 的关系

- **依赖 Phase 1**：策略 Token 的吊销/过期需要数据库表 `strategy_tokens` 和 `users`。
- **依赖 Phase 2**：FastAPI `Depends` 依赖注入使认证中间件更干净。
- Phase 3 应与 Phase 2 配合：认证逻辑作为独立 dependency，注入到各 router。

---

## 三、目标架构

```
backend/
├── auth/
│   ├── __init__.py
│   ├── jwt.py              # JWT 签发/验证/刷新
│   ├── password.py         # 密码哈希（bcrypt/argon2）
│   ├── dependencies.py     # JWT 依赖、策略 Token 依赖
│   └── models.py           # User, RefreshTokenBlacklist, StrategyToken
├── routers/
│   ├── auth.py             # /api/auth/* 路由
│   ├── server.py           # 管理接口使用 JWT
│   ├── strategy.py         # 管理接口使用 JWT
│   ├── order.py            # 管理接口使用 JWT
│   └── signal.py           # 下单接口使用策略 Token
└── services/
    ├── auth_service.py     # 认证业务逻辑
    └── strategy_token_service.py  # 策略 Token 管理
```

---

## 四、设计原则

1. **双轨认证**：
   - 管理端（人操作）：JWT Access + Refresh。
   - 远程信号（机器调用）：策略 Token。
2. **最小权限**：Access Token 有效期短（默认 30 分钟），Refresh Token 有效期长（默认 7 天）。
3. **可吊销**：Refresh Token 黑名单 + 策略 Token 吊销/过期。
4. **无状态验证**：JWT 验证不查询数据库，策略 Token 验证查询数据库。
5. **安全存储**：密码哈希存储，Token 只存 hash，明文只在生成时返回一次。

---

## 五、实施步骤

### Step 1：用户模型与策略 Token 模型（1-2 天）

依赖 Phase 1 的数据库基础设施。

#### 1.1 `users` 表

```sql
users
  id              UUID PK
  username        VARCHAR(64) UNIQUE NOT NULL
  password_hash   VARCHAR(128) NOT NULL
  is_active       BOOLEAN DEFAULT TRUE
  is_admin        BOOLEAN DEFAULT TRUE  -- 初期只有一个管理员
  created_at      TIMESTAMPTZ DEFAULT now()
  updated_at      TIMESTAMPTZ DEFAULT now()
```

#### 1.2 `refresh_token_blacklist` 表

```sql
refresh_token_blacklist
  id              UUID PK
  jti             VARCHAR(64) UNIQUE NOT NULL  -- JWT ID
  expires_at      TIMESTAMPTZ NOT NULL          -- 用于定期清理
  created_at      TIMESTAMPTZ DEFAULT now()
```

#### 1.3 `strategy_tokens` 表

已在 THINKING.md 中定义：

```sql
strategy_tokens
  id              UUID PK
  strategy_id     UUID FK -> strategies.id
  token_hash      VARCHAR(128) UNIQUE NOT NULL
  token_prefix    VARCHAR(16)
  expires_at      TIMESTAMPTZ
  revoked_at      TIMESTAMPTZ
  last_used_at    TIMESTAMPTZ
  created_at      TIMESTAMPTZ DEFAULT now()
```

### Step 2：JWT 工具层（1 天）

`backend/auth/jwt.py`：

```python
from datetime import datetime, timedelta
from jose import jwt, JWTError
from pydantic import BaseModel

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    sub: str          # user_id
    typ: str          # access / refresh
    jti: str          # JWT ID
    exp: datetime

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7

def create_access_token(user_id: str) -> str:
    jti = uuid.uuid4().hex
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "typ": "access", "jti": jti, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    jti = uuid.uuid4().hex
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "typ": "refresh", "jti": jti, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as e:
        raise TokenInvalidError(str(e))
```

### Step 3：认证服务（1-2 天）

`backend/services/auth_service.py`：

```python
from backend.auth.jwt import create_access_token, create_refresh_token, decode_token
from backend.auth.password import verify_password, hash_password

class AuthService:
    def __init__(self, user_repo, blacklist_repo):
        self._user_repo = user_repo
        self._blacklist_repo = blacklist_repo

    def authenticate(self, username: str, password: str) -> TokenPair:
        user = self._user_repo.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            raise AuthenticationError("用户名或密码错误")
        if not user.is_active:
            raise AuthenticationError("用户已禁用")
        return TokenPair(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id)
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        payload = decode_token(refresh_token)
        if payload.typ != "refresh":
            raise TokenInvalidError("不是 Refresh Token")
        if self._blacklist_repo.is_blacklisted(payload.jti):
            raise TokenInvalidError("Refresh Token 已吊销")
        return create_access_token(payload.sub)

    def logout(self, refresh_token: str) -> None:
        payload = decode_token(refresh_token)
        if payload.typ != "refresh":
            raise TokenInvalidError("不是 Refresh Token")
        self._blacklist_repo.add(payload.jti, payload.exp)
```

### Step 4：策略 Token 服务（1 天）

`backend/services/strategy_token_service.py`：

```python
import secrets
import hashlib

class StrategyTokenService:
    def __init__(self, token_repo):
        self._token_repo = token_repo

    def _hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_token(self, strategy_id: str) -> str:
        raw_token = secrets.token_hex(32)
        token_hash = self._hash(raw_token)
        self._token_repo.create(
            strategy_id=strategy_id,
            token_hash=token_hash,
            token_prefix=raw_token[:6],
        )
        return raw_token

    def validate_token(self, raw_token: str) -> Optional[StrategyToken]:
        token_hash = self._hash(raw_token)
        token = self._token_repo.get_by_hash(token_hash)
        if not token:
            return None
        if token.revoked_at:
            return None
        if token.expires_at and token.expires_at < datetime.utcnow():
            return None
        self._token_repo.update_last_used(token.id)
        return token

    def revoke_token(self, token_id: str) -> bool:
        return self._token_repo.revoke(token_id)

    def list_tokens(self, strategy_id: str):
        return self._token_repo.list_by_strategy(strategy_id)
```

### Step 5：FastAPI 认证依赖（1 天）

`backend/auth/dependencies.py`：

```python
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.typ != "access":
            raise HTTPException(status_code=401, detail="Token 类型错误")
    except TokenInvalidError:
        raise HTTPException(status_code=401, detail="无效的 Access Token")

    user = auth_service.get_user(payload.sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    return user

async def verify_strategy_token(
    x_token: str = Header(...),
    token_service: StrategyTokenService = Depends(get_strategy_token_service)
) -> StrategyToken:
    token = token_service.validate_token(x_token)
    if not token:
        raise HTTPException(status_code=401, detail="无效的策略 Token")
    return token
```

### Step 6：认证路由（0.5 天）

`backend/routers/auth.py`：

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth")

class LoginRequest(BaseModel):
    username: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/login")
async def login(data: LoginRequest,
                auth_service: AuthService = Depends(get_auth_service)):
    tokens = auth_service.authenticate(data.username, data.password)
    return {"success": True, "data": tokens.model_dump()}

@router.post("/refresh")
async def refresh(data: RefreshRequest,
                  auth_service: AuthService = Depends(get_auth_service)):
    access_token = auth_service.refresh_access_token(data.refresh_token)
    return {"success": True, "data": {"access_token": access_token}}

@router.post("/logout")
async def logout(data: RefreshRequest,
                 auth_service: AuthService = Depends(get_auth_service)):
    auth_service.logout(data.refresh_token)
    return {"success": True, "data": {"message": "已登出"}}
```

### Step 7：改造现有路由认证方式（1-2 天）

#### 7.1 管理接口改用 JWT

```python
# routers/strategy.py
@router.get("/strategies")
async def list_strategies(
    strategy_service: IStrategyService = Depends(get_strategy_service),
    current_user: User = Depends(get_current_user)
):
    return {"success": True, "data": strategy_service.list_strategies()}
```

需要改造的管理接口：

- `/api/start-server`
- `/api/stop-server`
- `/api/server-info`
- `/api/server-status`
- `/api/test-connection`
- `/api/account-asset`
- `/api/account-positions`
- `/api/strategies/*`
- `/api/orders`
- `/api/convert/*`
- `/api/docs/*`

#### 7.2 下单接口改用策略 Token

```python
# routers/signal.py
@router.post("/jukuan_order")
async def jukuan_order(
    request: dict,
    token: StrategyToken = Depends(verify_strategy_token),
    signal_service: ISignalService = Depends(get_signal_service)
):
    return signal_service.process_signal("jukuan_order", request, token)
```

### Step 8：前端适配（1-2 天）

`frontend/js/api.js`：

1. 登录后保存 `access_token` 和 `refresh_token` 到 `localStorage`。
2. 每次请求管理接口携带 `Authorization: Bearer {access_token}`。
3. 遇到 401 时，调用 `/api/auth/refresh` 换取新 Access Token。
4. Refresh Token 也过期时，跳转登录页。
5. 提供登录/登出 UI（可在配置面板中加入）。

```javascript
async function apiFetch(url, options = {}) {
  options.headers = options.headers || {};
  options.headers['Authorization'] = `Bearer ${getAccessToken()}`;

  let response = await fetch(url, options);

  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      options.headers['Authorization'] = `Bearer ${getAccessToken()}`;
      response = await fetch(url, options);
    } else {
      redirectToLogin();
    }
  }

  return response;
}
```

### Step 9：默认管理员初始化（0.5 天）

服务首次启动时，如果没有用户，创建一个默认管理员：

```python
# main.py startup
async def create_default_user():
    if not user_repo.get_by_username("admin"):
        user_repo.create(
            username="admin",
            password_hash=hash_password("admin"),  # 或从环境变量读取
            is_admin=True
        )
        logger.warning("已创建默认管理员 admin/admin，请尽快修改密码")
```

建议默认密码从环境变量 `DEFAULT_ADMIN_PASSWORD` 读取，否则随机生成并打印到日志。

### Step 10：测试（2-3 天）

#### 10.1 单元测试

- JWT 签发/验证/过期
- 密码哈希/验证
- AuthService 登录/刷新/登出
- StrategyTokenService 创建/验证/吊销

#### 10.2 集成测试

- 登录获取 Token
- 使用过期 Access Token 访问管理接口返回 401
- 使用 Refresh Token 刷新 Access Token
- 登出后 Refresh Token 无法刷新
- 使用吊销的策略 Token 下单返回 401
- 使用有效策略 Token 下单成功

#### 10.3 回归测试

- 确保原有 171 个测试通过（内存模式下认证逻辑可简化）。

---

## 六、关键决策

### 6.1 为什么管理端用 JWT，策略下单用独立 Token？

- 管理端是人操作，需要登录/登出/过期刷新。
- 策略 Token 是机器调用，简单、长有效期（或永久但可吊销）更符合远程信号源的使用习惯。
- 两者安全域不同：管理端泄露可修改配置，策略 Token 泄露只能下单。

### 6.2 为什么 Refresh Token 需要黑名单？

- JWT 本身无状态，登出后 token 仍然有效直到过期。
- Refresh Token 有效期较长（7 天），必须能吊销。
- Access Token 有效期短（30 分钟），可不黑名单，过期即失效。

### 6.3 为什么策略 Token 查询数据库验证？

- 策略 Token 需要支持吊销、过期、轮换，这些状态必须查询数据库。
- 策略 Token 调用频率较低（每次信号一次），查询数据库开销可接受。
- 未来可加入 Redis 缓存，但初期 SQLite 足够。

### 6.4 为什么 `SECRET_KEY` 必须修改默认值？

- 当前 `settings.py` 默认 `default-secret-key-change-in-production` 是安全风险。
- Phase 3 启动时应校验 SECRET_KEY 不是默认值，否则拒绝启动或打印严重警告。

### 6.5 是否引入 bcrypt/argon2？

- 是，使用 `passlib[bcrypt]` 进行密码哈希。
- bcrypt 成熟、安全、Python 生态支持好。

---

## 七、风险与回滚

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| JWT SECRET_KEY 泄露 | 高 | 强制从环境变量读取；启动时校验非默认值；定期轮换 |
| Refresh Token 黑名单表增长 | 中 | 定期清理过期黑名单记录；或设置 TTL |
| 策略 Token 轮换导致远程信号源失效 | 中 | 提供 Token 列表和轮换 UI；轮换时保留旧 Token 短暂有效期 |
| 前端 JWT 刷新逻辑引入循环 | 中 | 限制刷新重试次数；刷新失败跳转登录 |
| 密码哈希引入新依赖 | 低 | passlib + bcrypt 是标准方案 |

**回滚策略**：

- 保留旧的 `_verify_token` 和 `_verify_any_token` 逻辑，通过 feature flag `USE_JWT_AUTH` 切换。
- 如果 JWT 引入问题，可快速切回简单 Token 模式。

---

## 八、任务清单

### 模型

- [ ] 创建 `users` 表模型
- [ ] 创建 `refresh_token_blacklist` 表模型
- [ ] 确认 `strategy_tokens` 表模型（Phase 1 已完成）
- [ ] 生成 Alembic 迁移脚本

### JWT 与密码

- [ ] 实现 `backend/auth/jwt.py`
- [ ] 实现 `backend/auth/password.py`
- [ ] 配置 `SECRET_KEY` 和 Token 有效期

### 服务

- [ ] 实现 `backend/services/auth_service.py`
- [ ] 实现 `backend/services/strategy_token_service.py`

### 依赖

- [ ] 实现 `backend/auth/dependencies.py`
- [ ] 实现 `get_current_user` 依赖
- [ ] 实现 `verify_strategy_token` 依赖

### 路由

- [ ] 创建 `backend/routers/auth.py`
- [ ] 改造管理接口使用 JWT
- [ ] 改造下单接口使用策略 Token 验证

### 前端

- [ ] 前端保存和读取 Access/Refresh Token
- [ ] 请求自动携带 JWT
- [ ] 实现 Token 过期自动刷新
- [ ] 增加登录/登出 UI

### 初始化

- [ ] 首次启动创建默认管理员
- [ ] SECRET_KEY 默认值校验

### 测试

- [ ] JWT 单元测试
- [ ] 认证服务单元测试
- [ ] 策略 Token 服务单元测试
- [ ] 管理接口 JWT 集成测试
- [ ] 下单接口策略 Token 集成测试
- [ ] 完整回归测试

### 文档

- [ ] 更新 README 认证说明
- [ ] 更新 API 文档
- [ ] 更新 IMPLEMENTATION_PLAN

---

## 九、时间安排（预估 10-14 天）

| 阶段 | 时间 | 产出 |
|------|------|------|
| Step 1 模型 | 1-2 天 | users, refresh_token_blacklist 模型 |
| Step 2 JWT 工具 | 1 天 | jwt.py, password.py |
| Step 3 认证服务 | 1-2 天 | auth_service.py |
| Step 4 策略 Token 服务 | 1 天 | strategy_token_service.py |
| Step 5 依赖 | 1 天 | dependencies.py |
| Step 6 认证路由 | 0.5 天 | routers/auth.py |
| Step 7 路由改造 | 1-2 天 | 管理接口 JWT、下单接口策略 Token |
| Step 8 前端适配 | 1-2 天 | Token 管理、自动刷新、登录 UI |
| Step 9 默认用户 | 0.5 天 | 初始化逻辑 |
| Step 10 测试 | 2-3 天 | 单元/集成/回归测试 |
| 文档 | 0.5 天 | README、API 文档 |

> 注意：Phase 3 强烈依赖 Phase 1 的数据库和 Phase 2 的依赖注入，建议在 Phase 1/2 完成后开始。
