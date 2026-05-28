import argparse
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.server import QMTServer
from config.settings import settings

app = FastAPI(title="QMT Live Assistant - ")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

server: QMTServer = None


@app.get("/")
async def index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "QMT Live Assistant API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/server-info")
async def server_info():
    if server is None:
        return {
            "success": True,
            "data": {
                "running": False,
                "account_id": None,
                "qmt_path": None,
                "host": None,
                "port": None,
                "token": None,
            }
        }
    return {
        "success": True,
        "data": {
            "running": server.running,
            "account_id": server.account_id,
            "qmt_path": server.mini_qmt_path,
            "host": server.host,
            "port": server.port,
            "token": server.token,
        }
    }


@app.post("/api/start-server")
async def start_server(data: dict):
    global server

    if server is not None and server.running:
        raise HTTPException(status_code=400, detail="服务器已在运行中")

    account_id = data.get("account_id", "").strip()
    qmt_path = data.get("qmt_path", "").strip()
    host = data.get("host", "0.0.0.0")
    port = int(data.get("port", 8000))

    if not account_id:
        raise HTTPException(status_code=400, detail="请输入账户ID")
    if not qmt_path:
        raise HTTPException(status_code=400, detail="请输入QMT路径")

    server = QMTServer(
        account_id=account_id,
        mini_qmt_path=qmt_path,
        host=host,
        port=port,
    )

    server.init_and_setup(target_app=app)

    return {
        "success": True,
        "data": {
            "account_id": account_id,
            "qmt_path": qmt_path,
            "host": host,
            "port": port,
            "token": server.token,
        }
    }


@app.post("/api/stop-server")
async def stop_server():
    global server

    if server is None:
        raise HTTPException(status_code=400, detail="服务器未在运行")

    server.stop()
    server = None

    return {"success": True, "data": {"message": "服务器已停止"}}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="QMT Live Assistant Server")
    parser.add_argument("--host", default=settings.SERVER_HOST)
    parser.add_argument("--port", type=int, default=settings.SERVER_PORT)
    parser.add_argument("--account", default=settings.ACCOUNT_ID)
    parser.add_argument("--qmt-path", default=settings.MINI_QMT_PATH)
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    if args.account and args.qmt_path:
        srv = QMTServer(
            account_id=args.account,
            mini_qmt_path=args.qmt_path,
            host=args.host,
            port=args.port,
            token=args.token,
        )
        srv.run()
    else:
        uvicorn.run(app, host=args.host, port=args.port)
