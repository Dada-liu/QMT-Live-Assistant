import sys
import subprocess
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

from backend.logger import logger


def _create_icon_image(size=32):
    """用 Pillow 绘制 QMT 品牌托盘图标（圆角矩形 + Q 字母）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = 3
    radius = 6
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=radius,
        fill="#0052ff",
    )

    draw.text(
        (size // 2, size // 2 - 1),
        "Q",
        fill="white",
        anchor="mm",
    )

    return img


def _copy_to_clipboard(text: str):
    """跨平台复制文本到剪贴板"""
    platform = sys.platform
    try:
        if platform == "win32":
            subprocess.run("clip", input=text.encode(), check=False)
        elif platform == "darwin":
            subprocess.run("pbcopy", input=text.encode(), check=False)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode(), check=False)
    except FileNotFoundError:
        logger.warning("剪贴板工具不可用，无法复制 Token")


class TrayManager:
    """系统托盘管理器：图标 + 右键菜单 + 自动打开浏览器"""

    def __init__(self, server_url: str, token: str,
                 on_show=None, on_exit=None):
        self.server_url = server_url
        self.token = token
        self._on_show_callback = on_show
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
        if self._on_show_callback:
            self._on_show_callback()
        else:
            logger.info(f"打开管理界面: {self.server_url}")
            webbrowser.open(self.server_url)

    def _on_copy_token(self):
        _copy_to_clipboard(self.token)
        logger.info("Token 已复制到剪贴板")

    def _on_exit(self):
        logger.info("托盘退出")
        if self._on_exit_callback:
            self._on_exit_callback()
        if self._icon:
            self._icon.stop()

    def start(self):
        self._icon = pystray.Icon(
            "QMT Live Assistant",
            _create_icon_image(),
            "QMT Live Assistant",
            menu=self._build_menu(),
        )
        if not self._on_show_callback:
            webbrowser.open(self.server_url)
        threading.Thread(target=self._icon.run, daemon=True).start()
        logger.info("系统托盘已启动")

    def show_notification(self, title: str, message: str):
        if self._icon:
            self._icon.notify(message, title)

    def stop(self):
        if self._icon:
            self._icon.stop()
            logger.info("系统托盘已停止")


def run_tray_mode(host: str, port: int, token: str, on_show=None, on_exit=None):
    """便利函数：创建并启动托盘管理器"""
    server_url = f"http://127.0.0.1:{port}" if host == "0.0.0.0" else f"http://{host}:{port}"

    tray = TrayManager(server_url=server_url, token=token,
                       on_show=on_show, on_exit=on_exit)
    tray.start()
    return tray
