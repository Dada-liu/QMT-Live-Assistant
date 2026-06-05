# System Tray 桌面壳 — 实施方案

## 概述

新增 `backend/tray.py`，使用 `pystray` + `webbrowser` 实现轻量级 Windows 桌面壳：

- 双击 exe 启动 → 系统托盘出现图标 + 自动打开浏览器
- 右键托盘菜单：打开界面 / 复制 Token / 查看状态 / 退出
- 与现有 CLI 模式并存，不破坏任何现有功能

## 新增依赖

`requirements.txt` 追加：

```
pystray
pillow>=10.0.0
```

> `pystray` 在 Windows 上零依赖，macOS/Linux 需 `python-xlib`/`pyobjc`。`pillow` 用于生成托盘图标，项目已在用。

## 新增文件

### `backend/tray.py`

```
backend/tray.py    # 约 120 行，托盘管理逻辑
```

职责：
- `create_icon()` — 生成 32×32 托盘图标（Pillow 绘制 QMT 品牌图标）
- `TrayManager` 类 — 封装托盘生命周期
  - `__init__(server_url, token)` 
  - `start()` — 启动托盘 + 自动打开浏览器
  - `stop()` — 停止托盘
  - `_build_menu()` — 构建右键菜单
  - `_on_open()` — 打开管理界面
  - `_on_copy_token()` — 复制 Token 到剪贴板
  - `_on_exit()` — 退出应用
- `run_tray_mode(host, port, token)` — 便利函数，阻塞运行托盘

右键菜单项：
```
┌─────────────────────┐
│ 🟢 服务运行中       │  ← 不可点击，显示状态
│ ─────────────────── │
│ 🔗 打开管理界面     │  → 调用 webbrowser.open()
│ 📋 复制 Token       │  → 复制到剪贴板
│ ─────────────────── │
│ ❌ 退出             │  → 停止服务 + 退出托盘
└─────────────────────┘
```

核心代码结构：

```python
import pystray
import webbrowser
import threading
from PIL import Image, ImageDraw
from backend.logger import logger

def create_icon_image(size=32, color="#0052ff"):
    """用 Pillow 绘制简洁的 QMT 品牌图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 绘制圆角矩形 + 字母 Q
    ...

class TrayManager:
    def __init__(self, server_url: str, token: str, on_exit=None):
        self.server_url = server_url
        self.token = token
        self._on_exit_callback = on_exit
        self._icon = None

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("服务运行中", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开管理界面", self._on_open, default=True),
            pystray.MenuItem("复制 Token", self._on_copy_token),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_exit),
        )

    def _on_open(self):
        webbrowser.open(self.server_url)

    def _on_copy_token(self):
        import subprocess
        subprocess.run("clip", input=self.token.encode(), check=False)

    def _on_exit(self):
        if self._on_exit_callback:
            self._on_exit_callback()
        if self._icon:
            self._icon.stop()

    def start(self):
        self._icon = pystray.Icon(
            "QMT Live Assistant",
            create_icon_image(),
            "QMT Live Assistant",
            menu=self._build_menu(),
        )
        # 启动后自动打开浏览器
        webbrowser.open(self.server_url)
        # 托盘在独立线程运行
        threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self):
        if self._icon:
            self._icon.stop()
```

## 修改文件

### 1. `backend/main.py`

**改动点 ①**：新增 CLI 参数 `--tray`

```python
parser.add_argument("--tray", action="store_true", help="启动系统托盘模式（桌面壳）")
```

**改动点 ②**：新增 `_start_tray_mode()` 函数

```python
def _start_tray_mode(host, port, token):
    """桌面壳模式：托盘图标 + 自动打开浏览器"""
    from backend.tray import TrayManager

    server_url = f"http://{host}:{port}"
    if host == "0.0.0.0":
        server_url = f"http://127.0.0.1:{port}"

    def on_exit():
        nonlocal server
        if server:
            server.stop()

    tray = TrayManager(server_url=server_url, token=token, on_exit=on_exit)
    tray.start()

    # uvicorn 在主线程运行
    uvicorn.run(app, host=host, port=port, log_level="warning")
```

**改动点 ③**：修改 `__main__` 启动逻辑

当前逻辑：
```python
if args.account and args.qmt_path:
    server = QMTServer(...)
    server.run()          # 阻塞在 uvicorn.run()
else:
    uvicorn.run(app, ...) # 纯前端模式，无 QMT
```

修改为：
```python
if args.account and args.qmt_path:
    server = QMTServer(
        account_id=args.account,
        mini_qmt_path=args.qmt_path,
        host=args.host,
        port=args.port,
        token=args.token,
    )
    server.init_and_setup(target_app=app)

    if args.tray:
        _start_tray_mode(args.host, args.port, server.token)
    else:
        server.run()  # 保持现有 CLI 行为不变
else:
    uvicorn.run(app, host=args.host, port=args.port)
```

注意：`QMTServer.run()` 内部会调用 `init_and_setup()` + `uvicorn.run()`。在 tray 模式下，`init_and_setup()` 提前调用，`_start_tray_mode()` 中再调 `uvicorn.run()`，所以需要确保 `init_and_setup` 不会重复执行。当前 `run()` 是：

```python
def run(self):
    self.init_and_setup()   # ← tray 模式下已在外层调用
    uvicorn.run(self.app, host=self.host, port=self.port)
```

解决方案：在 `__main__` 中对 `server.run()` 的 tray 分支做调整，外层手动调 `init_and_setup()`，然后用 `uvicorn.run(app, ...)`（注意是全局 `app` 不是 `self.app`，因为 `init_and_setup(target_app=app)` 会把路由注册到全局 app）。

修改 `run()` 方法本身更干净：

```python
def run(self):
    """CLI 模式：自动初始化并启动"""
    self.init_and_setup()
    uvicorn.run(self.app, host=self.host, port=self.port)
```

`__main__` 中 tray 分支：

```python
server = QMTServer(...)
server.init_and_setup(target_app=app)  # tray 模式：手动初始化

if args.tray:
    _start_tray_mode(server.host, server.port, server.token)
else:
    uvicorn.run(app, host=server.host, port=server.port)
```

### 2. `requirements.txt`

```diff
+ pystray
+ pillow>=10.0.0
```

### 3. `README.md`（文档更新，可选）

在「运行」章节新增桌面壳模式说明：

```
### 桌面壳模式（Windows 推荐）

启动后自动在系统托盘显示图标，并打开管理界面：

```bash
python -m backend.main --account 1234567890 --qmt-path "C:\国金QMT交易端\userdata_mini" --tray
```

右键托盘图标可快速打开界面、复制 Token、退出服务。
```

## 不修改的文件

以下文件无任何改动：

- `backend/server.py`
- `backend/strategy_manager.py`
- `backend/signal_handler.py`
- `backend/qmt_client.py`
- `frontend/` 下所有文件
- `config/settings.py`
- `tests/` 下所有文件

## 影响范围总结

| 文件 | 操作 | 新增行数 |
|------|------|---------|
| `backend/tray.py` | **新增** | ~120 行 |
| `backend/main.py` | 修改 | +25 行，~5 行改动 |
| `requirements.txt` | 追加 | +2 行 |
| `README.md` | 更新（可选） | +8 行 |

总计净增约 155 行，改动 2 个文件 + 新增 1 个文件。所有现有功能和行为保持不变。

## 启动方式对比

| 方式 | 命令 | GUI | 托盘 | 自动打开浏览器 |
|------|------|-----|------|---------------|
| CLI（当前） | `python -m backend.main --account xxx --qmt-path yyy` | ✘ | ✘ | ✘ |
| 纯前端（当前） | `python -m backend.main --port 8000` | ✘ | ✘ | ✘ |
| **桌面壳（新增）** | `python -m backend.main --account xxx --qmt-path yyy --tray` | ✘ | ✔ | ✔ |

CLI 模式完全不变，`--tray` 是可选参数，不加就保持原有行为。

## 后续演进（不做入本次）

- `--autostart` 参数：写入 Windows 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- PyInstaller 打包：`pyinstaller --onefile --windowed --add-data "frontend;frontend" backend/main.py`
- `--silent` 参数：启动托盘但不打开浏览器（纯后台模式）
