import sys
import os
import subprocess
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


_SCRIPT_ROOT_PATH = '''
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
results["index"] = client.get("/qmt/").status_code
results["health"] = client.get("/qmt/health").status_code
results["server_info"] = client.get("/qmt/api/server-info").status_code
results["static_css"] = client.get("/qmt/static/styles.css").status_code
results["static_js"] = client.get("/qmt/static/js/app.js").status_code
results["docs_asset"] = client.get("/qmt/docs-assets/jq-send-signal-to-qmt/assets/step-1.png").status_code
routes = [r.path for r in main.app.routes]
results["static_mount"] = "/static" in routes
results["docs_mount"] = "/docs-assets" in routes

print(json.dumps(results))
'''


_SCRIPT_NO_ROOT_PATH = '''
import os
import sys
import json

sys.path.insert(0, os.getcwd())
os.environ["ROOT_PATH"] = ""

from backend import main
from fastapi.testclient import TestClient

main.server = None
client = TestClient(main.app)

results = {}
results["root_path"] = main.app.root_path
results["index"] = client.get("/").status_code
results["health"] = client.get("/health").status_code
results["server_info"] = client.get("/api/server-info").status_code
results["static_css"] = client.get("/static/styles.css").status_code
results["static_js"] = client.get("/static/js/app.js").status_code
results["docs_asset"] = client.get("/docs-assets/jq-send-signal-to-qmt/assets/step-1.png").status_code
routes = [r.path for r in main.app.routes]
results["static_mount"] = "/static" in routes
results["docs_mount"] = "/docs-assets" in routes

print(json.dumps(results))
'''


def _run_isolated(script: str):
    """在独立进程中启动应用并返回探针结果。

    每个脚本设置不同的 ROOT_PATH，因为 settings.ROOT_PATH 在模块导入时读取，
    静态挂载也在模块加载时完成，必须在独立子进程中测试不同场景。
    """
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if result.returncode != 0:
        raise AssertionError(f"子进程失败: {result.stderr}")
    last_line = result.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_app_root_path_is_set():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["root_path"] == "/qmt"


def test_health_under_root_path():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["health"] == 200


def test_api_under_root_path():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["server_info"] == 200


def test_index_under_root_path():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["index"] == 200


def test_static_mount_path_is_fixed():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["static_mount"] is True
    assert data["docs_mount"] is True


def test_static_assets_under_root_path():
    data = _run_isolated(_SCRIPT_ROOT_PATH)
    assert data["static_css"] == 200
    assert data["static_js"] == 200
    assert data["docs_asset"] == 200


def test_app_without_root_path():
    data = _run_isolated(_SCRIPT_NO_ROOT_PATH)
    assert data["root_path"] == ""
    assert data["index"] == 200
    assert data["health"] == 200
    assert data["server_info"] == 200


def test_static_assets_without_root_path():
    data = _run_isolated(_SCRIPT_NO_ROOT_PATH)
    assert data["static_mount"] is True
    assert data["docs_mount"] is True
    assert data["static_css"] == 200
    assert data["static_js"] == 200
    assert data["docs_asset"] == 200
