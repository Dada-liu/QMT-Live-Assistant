# PyWebView + PyInstaller 打包 — 实施方案

## 概述

在 `TRAY_PLAN.md` 的基础上，进一步实现：

1. **pywebview** 替代浏览器 — 用 Windows 原生 WebView2 窗口渲染前端，用户无感知是 Web 技术
2. **PyInstaller** 打包 — 输出单个 `.exe` 文件，无需安装 Python，双击即用

## 新增依赖

`requirements.txt` 追加（在 TRAY_PLAN 基础上）：

```
pywebview
pyinstaller>=6.0.0
```

> `pywebview` 在 Windows 上使用 Edge WebView2（Win10+ 预装），包体积 ~2MB。PyInstaller 仅开发时用，不打入生产依赖。

---

## Phase 1：pywebview 窗口壳

### 架构变化

```
TRAY_PLAN 架构（当前方案）        本方案架构
                          
┌─────────────┐          ┌─────────────────┐
│  Python 进程 │          │   Python 进程     │
│  ┌─────────┐ │          │  ┌─────────────┐ │
│  │ uvicorn │ │          │  │ uvicorn      │ │ ← 独立线程
│  │ :8000   │ │          │  │ :8000        │ │
│  └─────────┘ │          │  └──────┬──────┘ │
│  ┌─────────┐ │          │         │        │
│  │ Tray    │ │          │  ┌──────▼──────┐ │
│  │ Manager │ │          │  │ pywebview   │ │ ← 主线程（阻塞）
│  └─────────┘ │          │  │ 原生窗口     │ │   加载 localhost:8000
│       │      │          │  │ WebView2    │ │
│  自动打开    │          │  └──────┬──────┘ │
│  外部浏览器  │          │         │        │
└─────────────┘          │  ┌──────▼──────┐ │
                          │  │ Tray        │ │ ← 独立线程
                          │  │ Manager     │ │
                          │  └─────────────┘ │
                          └─────────────────┘

关键变化：
  1. pywebview 窗口替代外部浏览器
  2. 主线程跑 pywebview（阻塞），uvicorn 在后台线程
  3. 关闭窗口 ≠ 退出，最小化到托盘
  4. 托盘「打开界面」→ 恢复/激活已有窗口
```

### 新增文件

#### `backend/window.py`（约 180 行）

负责：
- 在后台线程启动 uvicorn
- 在前台启动 pywebview 原生窗口
- 窗口 → 托盘的交互逻辑
- 单实例检测（不重复打开窗口）

核心设计：

```python
import threading
import time
import webview
from backend.tray import TrayManager


class WindowManager:
    """管理 pywebview 窗口 + 后台 uvicorn 的生命周期"""

    def __init__(self, app, host: str, port: int, token: str, title="QMT Live Assistant"):
        self._app = app
        self._host = host
        self._port = port
        self._token = token
        self._title = title
        self._window = None
        self._tray = None
        self._server_ready = threading.Event()

    # ---- 服务启动 ----

    def _start_uvicorn(self):
        """在后台线程启动 FastAPI"""
        import uvicorn
        uvicorn.run(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )

    def _wait_for_server(self, timeout=10):
        """轮询等待服务就绪"""
        import urllib.request
        url = f"http://127.0.0.1:{self._port}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url, timeout=1)
                self._server_ready.set()
                return True
            except Exception:
                time.sleep(0.3)
        return False

    # ---- 窗口管理 ----

    def _on_closing(self):
        """窗口关闭 → 隐藏到托盘，不退出"""
        if self._window:
            self._window.hide()
        if self._tray:
            self._tray.show_notification("QMT Live Assistant", "已最小化到系统托盘")

    def _on_shown(self):
        """窗口显示时的回调"""
        self._window.evaluate_js("document.title = 'QMT Live Assistant'")

    def show_window(self):
        """显示/恢复窗口"""
        if self._window:
            self._window.show()
            self._window.restore()

    # ---- 生命周期 ----

    def start(self):
        """启动服务 + 窗口 + 托盘"""
        server_url = f"http://127.0.0.1:{self._port}"

        # 1. 启动 uvicorn 线程
        server_thread = threading.Thread(target=self._start_uvicorn, daemon=True)
        server_thread.start()

        # 2. 等待服务就绪
        if not self._wait_for_server():
            raise RuntimeError("服务启动超时")

        # 3. 启动托盘
        self._tray = TrayManager(
            server_url=server_url,
            token=self._token,
            on_show=self.show_window,  # ← 托盘「打开」→ 恢复窗口
            on_exit=self._exit_app,
        )
        self._tray.start()

        # 4. 启动原生窗口（阻塞主线程）
        self._window = webview.create_window(
            title=self._title,
            url=server_url,
            width=1200,
            height=800,
            min_size=(900, 600),
            confirm_close=False,  # 关闭行为由我们控制
            text_select=True,
        )

        self._window.events.closing += self._on_closing
        self._window.events.shown += self._on_shown

        webview.start(gui='edgechromium')  # ← 强制 Win10+ 用 WebView2

    def _exit_app(self):
        """完全退出"""
        if self._tray:
            self._tray.stop()
        # 窗口关闭
        if self._window:
            self._window.destroy()
        # uvicorn 线程是 daemon，进程退出时自动终止
        import os
        os._exit(0)
```

### 修改文件

#### 1. `backend/tray.py`（微调）

增加 `on_show` 回调参数，使托盘「打开管理界面」-> 恢复已有窗口而非打开浏览器：

```python
class TrayManager:
    def __init__(self, server_url: str, token: str, 
                 on_show=None, on_exit=None):
        self.server_url = server_url
        self.token = token
        self._on_show_callback = on_show   # 新增
        self._on_exit_callback = on_exit
        self._icon = None
        self._use_browser = on_show is None  # 无 on_show 则降级为浏览器

    def _on_open(self):
        if self._on_show_callback:
            self._on_show_callback()        # pywebview 模式：恢复窗口
        else:
            import webbrowser
            webbrowser.open(self.server_url) # 浏览器模式（兼容 TRAY_PLAN）
```

#### 2. `backend/main.py`（修改）

新增 `--window` 参数，与 `--tray` 独立：

```python
parser.add_argument("--tray", action="store_true", 
                    help="启动系统托盘模式")
parser.add_argument("--window", action="store_true",
                    help="启动原生桌面窗口模式（需 pywebview）")

# --window 优先级高于 --tray
# 不加任何参数 = CLI 模式（当前行为）
```

启动逻辑：

```python
if args.account and args.qmt_path:
    server = QMTServer(...)
    server.init_and_setup(target_app=app)

    if args.window:
        _start_window_mode(server.host, server.port, server.token)
    elif args.tray:
        _start_tray_mode(server.host, server.port, server.token)
    else:
        uvicorn.run(app, host=server.host, port=server.port)
```

新增 `_start_window_mode()`：

```python
def _start_window_mode(host, port, token):
    """原生桌面窗口模式：pywebview + 托盘"""
    from backend.window import WindowManager
    wm = WindowManager(app=app, host=host, port=port, token=token)
    wm.start()
```

#### 3. `requirements.txt`

```
# 追加
pywebview

# 开发依赖（不打入 exe）
pyinstaller>=6.0.0
```

---

## Phase 2：PyInstaller 打包

### 目标

将整个项目打包为单个 `.exe`，用户无需安装 Python、pip、任何依赖。

### 2.1 目录结构约定

打包后的 exe 解压到临时目录运行，`sys._MEIPASS` 指向该目录。前端文件需要随 exe 一起打包。

```
打包前                              打包后
──                                  ──
backend/                            QMT-Live-Assistant.exe   (约 35-50 MB)
frontend/                           │
  index.html                        │ 双击运行
  styles.css                        │
  js/                               ▼
  ...                          ┌─────────────────┐
                               │ pywebview 窗口  │
                               │ (WebView2)      │
                               │ 加载内嵌前端    │
                               └─────────────────┘
```

### 2.2 修改 `backend/main.py` — 前端路径适配

当前代码写死相对路径，打包后 `__file__` 无效，需要改为运行时解析：

```python
import sys
from pathlib import Path

def _get_frontend_dir() -> str:
    """获取前端目录路径（兼容开发模式 + PyInstaller 打包模式）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包：前端文件在 _MEIPASS/frontend
        base = Path(sys._MEIPASS)
    else:
        # 开发模式：backend/../frontend
        base = Path(__file__).resolve().parent.parent
    frontend = base / "frontend"
    if frontend.exists():
        return str(frontend)
    raise FileNotFoundError("前端目录不存在，请检查打包配置")


def _get_docs_dir() -> str:
    """获取文档目录路径"""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    docs = base / "docs"
    return str(docs) if docs.exists() else ""


# 替换原来的 os.path.dirname(os.path.dirname(__file__))
frontend_dir = _get_frontend_dir()
docs_dir = _get_docs_dir()
```

### 2.3 新增 `pyinstaller.spec`

PyInstaller 的 spec 文件精确控制打包行为：

```python
# pyinstaller.spec
# 使用方式：pyinstaller pyinstaller.spec

import sys
from pathlib import Path

# 项目根目录（spec 文件所在目录）
ROOT = Path(SPECPATH)

a = Analysis(
    # 入口脚本
    ['backend/main.py'],

    # 不使用 UPX（避免杀软误报）
    # pathex 指向项目根，确保 relative import 正确
    pathex=[str(ROOT)],

    binaries=[],

    datas=[
        # 前端文件打包进 exe
        (str(ROOT / 'frontend'), 'frontend'),
        # 文档
        (str(ROOT / 'docs'), 'docs'),
    ],

    # 隐藏导入（pywebview/FastAPI 的动态导入链）
    hiddenimports=[
        # FastAPI 全家桶
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette',
        'starlette.middleware',
        'starlette.middleware.cors',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',

        # Pydantic
        'pydantic',
        'pydantic.deprecated',
        'pydantic.deprecated.copy_internals',

        # pywebview
        'webview',
        'webview.platforms',
        'webview.platforms.edgechromium',

        # 项目内部模块
        'backend',
        'backend.server',
        'backend.qmt_client',
        'backend.signal_handler',
        'backend.strategy_manager',
        'backend.utils',
        'backend.logger',
        'backend.constants',
        'backend.qmt_xtconstant',
        'backend.mock_xtquant',
        'config',
        'config.settings',

        # pystray（托盘）
        'pystray',
        'pystray._win32',

        # Pillow
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的重型模块，缩小体积
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'jedi',
        'IPython',
        'sqlalchemy',
        'psycopg2',
        'mysql',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ---- 针对 --window 模式做入口点增强 ----
# 修改入口脚本，让 exe 默认以 --window 模式启动
# 同时支持 CLI 参数覆盖

# 方式：在运行时解析参数，不加 --window 就保持 CLI 行为
# 开发用 python -m backend.main，打包后默认等价于 python -m backend.main --window

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QMT-Live-Assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # ← 无控制台窗口（GUI 应用）
    icon=str(ROOT / 'assets' / 'icon.ico'),  # 需要准备图标文件
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### 2.4 应用图标

需要准备 `assets/icon.ico`（建议 256×256，含 48/32/16 多尺寸）。

临时方案：用 Pillow 生成基础图标。

```python
# scripts/generate_icon.py（一次性运行）
from PIL import Image, ImageDraw

def create_icon():
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([16, 16, 240, 240], radius=48, fill="#0052ff")
    draw.text((128, 128), "QMT", fill="white", anchor="mm")
    img.save("assets/icon.png")
    # 转 ico 需额外工具或在线转换
```

### 2.5 打包命令

```bash
# 安装打包工具
pip install pyinstaller

# 生成 spec 文件（首次）
pyi-makespec --name "QMT-Live-Assistant" \
  --add-data "frontend;frontend" \
  --add-data "docs;docs" \
  --hidden-import fastapi \
  --hidden-import uvicorn \
  --hidden-import webview \
  --hidden-import pystray \
  --hidden-import backend \
  --windowed \
  backend/main.py

# 用自定义 spec 打包
pyinstaller pyinstaller.spec --clean --noconfirm

# 输出位置：dist/QMT-Live-Assistant.exe
```

### 2.6 修改 `backend/main.py` — 打包模式默认参数

打包后的 exe 双击运行时没有命令行参数，需要给默认行为。加一行检测：

```python
if __name__ == "__main__":
    import sys, argparse

    # PyInstaller 打包后双击运行时：无命令行参数
    # → 默认启用 --window 模式（需要 --account 和 --qmt-path 则从配置文件/环境变量读取）
    _is_frozen = getattr(sys, 'frozen', False)
    _has_args = len(sys.argv) > 1

    parser = argparse.ArgumentParser(...)
    parser.add_argument("--host", default=settings.SERVER_HOST)
    parser.add_argument("--port", type=int, default=settings.SERVER_PORT)
    parser.add_argument("--account", default=settings.ACCOUNT_ID)
    parser.add_argument("--qmt-path", default=settings.MINI_QMT_PATH)
    parser.add_argument("--token", default=None)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--window", action="store_true")
    args = parser.parse_args()

    # 打包后的 exe 双击无参数时：如果有 account + qmt-path 配置则默认用 window 模式
    if _is_frozen and not _has_args:
        if args.account and args.qmt_path:
            args.window = True
        else:
            # 无配置 → 打开纯前端窗口，让用户填写配置
            args.window = True

    # ... 后续启动逻辑
```

---

## 启动方式全矩阵

| 命令/操作 | 模式 | 窗口 | 托盘 | 浏览器 |
|-----------|------|------|------|--------|
| `python -m backend.main` | 纯前端 | ✘ | ✘ | 手动打开 |
| `python -m backend.main --account xxx --qmt-path xxx` | CLI 服务 | ✘ | ✘ | 手动打开 |
| `python -m backend.main --account xxx --qmt-path xxx --tray` | 托盘模式 | ✘ | ✔ | 自动打开 |
| `python -m backend.main --account xxx --qmt-path xxx --window` | **原生窗口** | ✔ WebView2 | ✔ | ✘ |
| `python -m backend.main --window` | 纯前端窗口 | ✔ WebView2 | ✔ | ✘ |
| 双击 `QMT-Live-Assistant.exe` | 打包默认 = `--window` | ✔ | ✔ | ✘ |
| `QMT-Live-Assistant.exe --account xxx --qmt-path xxx` | CLI 参数覆盖 | ✘ | ✘ | ✘ |

---

## 影响范围总结

### Phase 1（pywebview）

| 文件 | 操作 | 新增行数 |
|------|------|---------|
| `backend/window.py` | **新增** | ~180 行 |
| `backend/tray.py` | 修改 | +15 行（增加 on_show 回调和降级逻辑） |
| `backend/main.py` | 修改 | +25 行（`--window` 参数 + `_start_window_mode`） |
| `requirements.txt` | 追加 | +1 行 |

Phase 1 净增约 220 行，改动 2 个文件 + 新增 1 个文件。

### Phase 2（PyInstaller）

| 文件 | 操作 | 新增行数 |
|------|------|---------|
| `pyinstaller.spec` | **新增** | ~80 行 |
| `backend/main.py` | 修改 | +20 行（前端路径适配 + 打包默认行为） |
| `assets/icon.ico` | **新增** | 二进制（需准备） |

Phase 2 净增约 100 行 + 1 个图标文件。

### 全部改动汇总

```
新增文件（3 个）：
  backend/window.py        ~180 行
  pyinstaller.spec         ~80 行
  assets/icon.ico          二进制

修改文件（3 个）：
  backend/tray.py           +15 行
  backend/main.py           +45 行
  requirements.txt          +2 行

不修改（0 改动）：
  backend/server.py
  backend/strategy_manager.py
  backend/signal_handler.py
  backend/qmt_client.py
  frontend/ 全部文件
  config/settings.py
  tests/ 全部文件
```

---

## 注意事项

### pywebview

1. **WebView2 运行时**：Windows 10 1903+ 或 Windows 11 已预装。若缺失，pywebview 会提示安装，仅需一次。
2. **console 关闭问题**：打包时必须用 `console=False`（`--windowed`），否则会多个控制台窗口。
3. **窗口关闭 = 隐藏到托盘**：这是桌面应用的常规行为。通过 `confirm_close=False` + `events.closing` 实现。
4. **debug 模式**：开发时右键 pywebview 窗口可打开 Chromium DevTools（设置 `webview.start(debug=True)`）。

### PyInstaller

1. **杀软误报**：PyInstaller 打包的 exe 可能被杀软误报。对策：
   - 不启用 UPX 压缩
   - 提交到 Microsoft Defender 白名单
   - 代码签名证书（EV Code Signing）是商业化的必需品
2. **包体积**：预计 35-50 MB（含 Python 解释器 + FastAPI + uvicorn + pywebview + pystray）。
3. **启动速度**：首次启动 ~3-5 秒（解压 + Python 初始化），之后 ~2 秒。
4. **xtquant SDK**：xtquant 是外部依赖，不打包进 exe。用户仍需安装 QMT 客户端，exe 只需知道 QMT 路径即可调用其 SDK。
5. **跨 Python 版本**：打包时用 Python 3.10（QMT SDK 可能仅支持特定版本）。

### 商业化发布前必做

- [ ] 申请 EV Code Signing 证书（约 ¥2000-4000/年）
- [ ] 准备安装程序（NSIS / Inno Setup），而非裸 exe
- [ ] 安装程序加入 License Agreement + 免责声明
- [ ] 自动检测本地 Python/QMT 依赖状态
- [ ] 首次启动引导（填写 account_id、qmt_path）
