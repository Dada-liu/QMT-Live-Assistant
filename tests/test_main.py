import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from backend import main


@pytest.fixture
def client():
    # 确保每个测试开始时全局 server 为 None
    main.server = None
    with TestClient(main.app) as c:
        yield c
    if main.server is not None:
        import asyncio
        asyncio.run(main.server.stop_async())
        main.server = None


def test_health_no_server(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["server_running"] is False
    assert data["qmt_connected"] is False
    assert data["connection_state"] == "disconnected"


def test_server_info_no_server(client):
    response = client.get("/api/server-info")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["running"] is False
    assert data["qmt_connected"] is False
    assert data["connection_state"] == "disconnected"
    assert data["reconnect_attempts"] == 0


def test_start_server(client):
    response = client.post(
        "/api/start-server",
        json={
            "account_id": "test_account",
            "qmt_path": "/tmp/mock_qmt",
            "host": "127.0.0.1",
            "port": 8002,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["running"] is True
    assert data["data"]["qmt_connected"] is True
    assert data["data"]["connection_state"] == "connected"
    assert data["data"]["account_id"] == "test_account"
    assert "token" in data["data"]


def test_stop_server(client):
    start = client.post(
        "/api/start-server",
        json={
            "account_id": "test_account",
            "qmt_path": "/tmp/mock_qmt",
            "host": "127.0.0.1",
            "port": 8003,
        },
    )
    assert start.status_code == 200
    token = start.json()["data"]["token"]

    response = client.post(
        "/api/stop-server",
        headers={"X-Token": token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "服务器已停止" in data["data"]["message"]


def test_stop_server_without_running(client):
    response = client.post(
        "/api/stop-server",
        headers={"X-Token": "dummy"},
    )
    assert response.status_code == 401
    assert "无效的Token" in response.json()["detail"]


def test_list_docs(client):
    response = client.get("/api/docs")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) > 0


def test_get_doc_not_found(client):
    response = client.get("/api/docs/nonexistent-doc")
    assert response.status_code == 404


def test_get_existing_doc(client, tmp_path):
    from backend import main
    original_docs_dir = main.docs_dir
    try:
        main.docs_dir = str(tmp_path)
        doc_dir = tmp_path / "qmt-live-assistant-usage"
        doc_dir.mkdir()
        (doc_dir / "content.md").write_text("# Hello", encoding="utf-8")

        response = client.get("/api/docs/qmt-live-assistant-usage")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Hello" in data["data"]["content"]
    finally:
        main.docs_dir = original_docs_dir
