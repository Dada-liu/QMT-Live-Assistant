import os
import sys
import threading
import time

from pathlib import Path


def _setup_webview2_runtime():
    """设置 WebView2 运行时路径，优先使用打包内置版本"""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent

    bundled = base / 'webview2'
    if bundled.exists() and (bundled / 'msedgewebview2.exe').exists():
        os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = str(bundled)


_setup_webview2_runtime()

import webview

from backend.logger import logger


class WindowManager:
    """管理 pywebview 窗口 + 后台 uvicorn 的生命周期"""

    def __init__(self, app, host: str, port: int, token: str = None,
                 title: str = "QMT Live Assistant"):
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
        import uvicorn
        uvicorn.run(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )

    def _wait_for_server(self, timeout: int = 10):
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
        if self._window:
            self._window.hide()
        if self._tray:
            self._tray.show_notification(
                "QMT Live Assistant",
                "已最小化到系统托盘",
            )

    def show_window(self):
        if self._window:
            self._window.show()
            self._window.restore()

    # ---- 生命周期 ----

    def start(self):
        server_url = f"http://127.0.0.1:{self._port}"

        server_thread = threading.Thread(target=self._start_uvicorn, daemon=True)
        server_thread.start()

        if not self._wait_for_server():
            raise RuntimeError("服务启动超时")

        from backend.tray import TrayManager

        self._tray = TrayManager(
            server_url=server_url,
            token=self._token or "",
            on_show=self.show_window,
            on_exit=self._exit_app,
        )
        self._tray.start()

        self._window = webview.create_window(
            title=self._title,
            url=server_url,
            width=1200,
            height=800,
            min_size=(900, 600),
            confirm_close=False,
            text_select=True,
        )

        self._window.events.closing += self._on_closing

        webview.start(gui='edgechromium', debug=True)

    def _exit_app(self):
        if self._tray:
            self._tray.stop()
        if self._window:
            self._window.destroy()
        os._exit(0)
