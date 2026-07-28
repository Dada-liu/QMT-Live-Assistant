import sys
import os
import subprocess
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


_SCRIPT = '''
import os
import sys
import json

sys.path.insert(0, os.getcwd())
os.environ["ROOT_PATH"] = "/qmt"

from backend import main
from fastapi.testclient import TestClient

main.server = None
client = TestClient(main.app)

results = {}
results["root_path"] = main.app.root_path
results["health"] = client.get("/qmt/health").status_code
results["server_info"] = client.get("/qmt/api/server-info").status_code
routes = [r.path for r in main.app.routes]
results["static_mount"] = "/qmt/static" in routes

print(json.dumps(results))
'''


def _run_isolated():
    """在独立进程中启动带有 ROOT_PATH=/qmt 的应用并返回探针结果。"""
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if result.returncode != 0:
        raise AssertionError(f"子进程失败: {result.stderr}")
    last_line = result.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_app_root_path_is_set():
    data = _run_isolated()
    assert data["root_path"] == "/qmt"


def test_health_under_root_path():
    data = _run_isolated()
    assert data["health"] == 200


def test_static_mount_path_includes_root_path():
    data = _run_isolated()
    assert data["static_mount"] is True


def test_api_under_root_path():
    data = _run_isolated()
    assert data["server_info"] == 200
