"""FastAPI 应用入口与 CLI 启动器。

负责注册 HTTP 路由、启动/停止 QMT 服务器、
提供系统托盘模式与原生桌面窗口模式入口。
"""
import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.server import QMTServer
from backend.db.base import SessionLocal
from backend.db.repositories import (
    SQLAlchemyStrategyRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyAccountRepository,
    SQLAlchemySignalLogRepository,
    SQLAlchemySettingsRepository,
)
from config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：CLI 传入的 server 在此启动，关闭时清理。"""
    global server
    if server is not None and not server.running:
        await server.init_and_setup_async(target_app=app)
    yield
    if server is not None:
        await server.stop_async()
        server = None


app = FastAPI(title="QMT Live Assistant", lifespan=lifespan, root_path=settings.ROOT_PATH)

_allow_origins = [o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
_allow_credentials = settings.CORS_ALLOW_CREDENTIALS.lower() in ("true", "1", "yes")
# CORS 规范不允许 origins 为 * 的同时允许 credentials
if "*" in _allow_origins and _allow_credentials:
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins or ["*"],
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _create_repositories(session):
    """根据配置创建 Repository。若 PERSISTENCE_MODE=memory 返回 None，使用内存实现。"""
    if settings.PERSISTENCE_MODE == "memory":
        return None, None, None, None, None, None
    return (
        session,
        SQLAlchemyStrategyRepository(session),
        SQLAlchemyOrderRepository(session),
        SQLAlchemyAccountRepository(session),
        SQLAlchemySignalLogRepository(session),
        SQLAlchemySettingsRepository(session),
    )


def _get_frontend_dir() -> str:
    """获取前端目录路径（兼容开发模式 + PyInstaller 打包模式）"""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
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


frontend_dir = _get_frontend_dir()
if os.path.exists(frontend_dir):
    # 固定挂载到 /static；FastAPI root_path 与 nginx 子路径代理会协同剥离前缀
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

docs_dir = _get_docs_dir()
if docs_dir and os.path.exists(docs_dir):
    # 文档静态资源同样固定挂载到 /docs-assets
    app.mount("/docs-assets", StaticFiles(directory=docs_dir), name="docs-assets")

DOCS_ALLOWED = ['jq-send-signal-to-qmt', 'qmt-live-assistant-usage']

server: QMTServer = None


async def verify_server_token(x_token: str = Header(...)):
    if server is None or x_token != server.token:
        raise HTTPException(status_code=401, detail="无效的Token")
    return x_token


@app.get("/")
async def index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "QMT Live Assistant API", "version": "1.0.0"}


@app.get("/health")
async def health():
    qmt_connected = False
    connection_state = "disconnected"
    server_running = server is not None and server.running
    if server_running:
        qmt_connected = server.qmt_connected
        connection_state = server.connection_state
    return {
        "status": "healthy",
        "server_running": server_running,
        "qmt_connected": qmt_connected,
        "connection_state": connection_state,
        "version": "1.0.0",
    }


@app.get("/api/server-info")
async def server_info():
    if server is None:
        return {
            "success": True,
            "data": {
                "running": False,
                "qmt_connected": False,
                "connection_state": "disconnected",
                "last_connection_error": None,
                "reconnect_attempts": 0,
                "account_id": None,
                "qmt_path": None,
                "host": None,
                "port": None,
            }
        }
    return {
        "success": True,
        "data": {
            "running": server.running,
            "qmt_connected": server.qmt_connected,
            "connection_state": server.connection_state,
            "last_connection_error": server.last_connection_error,
            "reconnect_attempts": server.reconnect_attempts,
            "account_id": server.account_id,
            "qmt_path": server.mini_qmt_path,
            "host": server.host,
            "port": server.port,
        }
    }


@app.post("/api/start-server")
async def start_server(data: dict):
    global server

    if server is not None and server.running:
        raise HTTPException(status_code=400, detail="服务器已在运行中")

    account_id = data.get("account_id", "").strip()
    qmt_path = data.get("qmt_path", "").strip()
    host = data.get("host", settings.SERVER_HOST)
    if not host:
        host = settings.SERVER_HOST
    port = int(data.get("port", settings.SERVER_PORT))

    if not account_id:
        raise HTTPException(status_code=400, detail="请输入账户ID")
    if not qmt_path:
        raise HTTPException(status_code=400, detail="请输入QMT路径")

    db_session = SessionLocal() if settings.PERSISTENCE_MODE != "memory" else None
    (
        _,
        strategy_repository,
        order_repository,
        account_repository,
        signal_log_repository,
        settings_repository,
    ) = _create_repositories(db_session)

    server = QMTServer(
        account_id=account_id,
        mini_qmt_path=qmt_path,
        host=host,
        port=port,
        strategy_repository=strategy_repository,
        order_repository=order_repository,
        account_repository=account_repository,
        signal_log_repository=signal_log_repository,
        settings_repository=settings_repository,
        db_session=db_session,
    )

    try:
        await server.init_and_setup_async(target_app=app)
    except ConnectionError as e:
        return {
            "success": False,
            "detail": f"QMT连接失败: {str(e)}",
        }

    return {
        "success": True,
        "data": {
            "running": server.running,
            "qmt_connected": server.qmt_connected,
            "connection_state": server.connection_state,
            "account_id": account_id,
            "qmt_path": qmt_path,
            "host": host,
            "port": port,
            "token": server.token,
        }
    }


@app.get("/api/docs")
async def list_docs():
    return {
        "success": True,
        "data": [
            {
                "id": "qmt-live-assistant-usage",
                "title": "QMT-Live-Assistant 使用指南",
                "summary": "了解如何安装、配置和使用 QMT-Live-Assistant 进行远程信号下单。"
            },
            {
                "id": "jq-send-signal-to-qmt",
                "title": "聚宽如何发送信号给 QMT-Live-Assistant",
                "summary": "从聚宽回测、模拟盘，将信号推送到 QMT-Live-Assistant。"
            }
        ]
    }


@app.get("/api/docs/{doc_name}")
async def get_doc(doc_name: str):
    if doc_name not in DOCS_ALLOWED:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc_path = os.path.join(docs_dir, doc_name, "content.md")
    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail="文档不存在")

    with open(doc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    _docs_root = f"{settings.ROOT_PATH}/docs-assets" if settings.ROOT_PATH else "/docs-assets"
    content = content.replace(f"](assets/", f"]({_docs_root}/{doc_name}/assets/")

    return {"success": True, "data": {"name": doc_name, "content": content}}


@app.post("/api/stop-server")
async def stop_server(_token: str = Depends(verify_server_token)):
    global server

    if server is None:
        raise HTTPException(status_code=400, detail="服务器未在运行")

    await server.stop_async()
    server = None

    return {"success": True, "data": {"message": "服务器已停止"}}


def _start_tray_mode(host, port, token):
    """桌面壳模式：托盘图标 + 自动打开浏览器"""
    import uvicorn
    from backend.tray import run_tray_mode

    def on_exit():
        if server:
            server.stop()

    run_tray_mode(host=host, port=port, token=token, on_exit=on_exit)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _start_window_mode(host, port, token):
    """原生桌面窗口模式：pywebview + 托盘，失败时降级到 tray 模式"""
    import traceback
    from backend.logger import logger

    try:
        from backend.window import WindowManager
        wm = WindowManager(app=app, host=host, port=port, token=token)
        wm.start()
    except Exception as e:
        logger.warning(f"窗口模式启动失败，降级到托盘模式: {e}")
        traceback.print_exc()
        _start_tray_mode(host, port, token)


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="QMT Live Assistant Server")
    parser.add_argument("--host", default=settings.SERVER_HOST)
    parser.add_argument("--port", type=int, default=settings.SERVER_PORT)
    parser.add_argument("--account", default=settings.ACCOUNT_ID)
    parser.add_argument("--qmt-path", default=settings.MINI_QMT_PATH)
    parser.add_argument("--token", default=None)
    parser.add_argument("--tray", action="store_true", help="启动系统托盘模式（桌面壳）")
    parser.add_argument("--window", action="store_true",
                        help="启动原生桌面窗口模式（需 pywebview）")
    args = parser.parse_args()

    _is_frozen = getattr(sys, 'frozen', False)
    _has_args = len(sys.argv) > 1
    if _is_frozen and not _has_args:
        if args.account and args.qmt_path:
            args.window = True
        else:
            args.window = True

    if args.account and args.qmt_path:
        db_session = SessionLocal() if settings.PERSISTENCE_MODE != "memory" else None
        (
            _,
            strategy_repository,
            order_repository,
            account_repository,
            signal_log_repository,
            settings_repository,
        ) = _create_repositories(db_session)
        server = QMTServer(
            account_id=args.account,
            mini_qmt_path=args.qmt_path,
            host=args.host,
            port=args.port,
            token=args.token,
            strategy_repository=strategy_repository,
            order_repository=order_repository,
            account_repository=account_repository,
            signal_log_repository=signal_log_repository,
            settings_repository=settings_repository,
            db_session=db_session,
        )

        if args.window:
            _start_window_mode(args.host, args.port, server.token)
        elif args.tray:
            _start_tray_mode(args.host, args.port, server.token)
        else:
            uvicorn.run(app, host=server.host, port=server.port)
    else:
        if args.window:
            _start_window_mode(args.host, args.port, None)
        else:
            uvicorn.run(app, host=args.host, port=args.port)
