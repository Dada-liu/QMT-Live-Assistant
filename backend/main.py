import argparse
import os

from fastapi import FastAPI, HTTPException, Header, Depends
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

docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
if os.path.exists(docs_dir):
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
            "running": server.running,
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
                "title": "聚宽如何发送信号到 QMT",
                "summary": "从聚宽研究/回测到云服务器部署，完整实现远程信号推送到 QMT-Live-Assistant。"
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

    print('doc: ', content)
    content = content.replace(f"](assets/", f"](/docs-assets/{doc_name}/assets/")

    return {"success": True, "data": {"name": doc_name, "content": content}}


@app.post("/api/stop-server")
async def stop_server(_token: str = Depends(verify_server_token)):
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
        server = QMTServer(
            account_id=args.account,
            mini_qmt_path=args.qmt_path,
            host=args.host,
            port=args.port,
            token=args.token,
        )
        server.run()
    else:
        uvicorn.run(app, host=args.host, port=args.port)
