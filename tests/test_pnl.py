import sys
import os
import asyncio
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.server import QMTServer
from backend.db.base import Base
from backend.db.models.asset_snapshot import AssetSnapshotModel  # noqa: F401 注册到 metadata
from backend.db.repositories.asset_snapshot import (
    InMemoryAssetSnapshotRepository,
    SQLAlchemyAssetSnapshotRepository,
)
from backend.utils import (
    is_trading_time,
    compute_daily_returns,
    compute_curve,
    compound_returns,
    compute_monthly_returns,
    compute_yearly_returns,
)


def _start_server(server):
    """在独立线程的事件循环中启动 QMTServer，供同步 TestClient 使用。"""
    loop = asyncio.new_event_loop()
    server._test_loop = loop
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.init_and_setup_async())
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    for _ in range(100):
        if server.qmt_connected:
            break
        time.sleep(0.05)
    if not server.qmt_connected:
        raise RuntimeError("测试服务器未能连接到 QMT")
    return loop, thread


def _stop_server(server, loop, thread):
    def schedule_stop():
        asyncio.create_task(server.stop_async())

    loop.call_soon_threadsafe(schedule_stop)
    for _ in range(50):
        if not server.running:
            break
        time.sleep(0.05)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


@pytest.fixture
def server():
    srv = QMTServer(
        account_id="test_account",
        mini_qmt_path="/tmp/mock_qmt",
        host="127.0.0.1",
        port=8011,
        asset_snapshot_repository=InMemoryAssetSnapshotRepository(),
    )
    # 快照 loop 启动后立即执行首次采集，与任务取消存在竞态；
    # 启动期间强制为非交易时段，确保不会自动写入快照干扰断言
    with patch("backend.server.is_trading_time", return_value=False):
        loop, thread = _start_server(srv)
    if srv._snapshot_task is not None:
        loop.call_soon_threadsafe(srv._snapshot_task.cancel)
        for _ in range(100):
            if srv._snapshot_task is None or srv._snapshot_task.done():
                break
            time.sleep(0.01)
    yield srv
    _stop_server(srv, loop, thread)


@pytest.fixture
def client(server):
    return TestClient(server.app)


def _snapshots_repo(server):
    return server._asset_snapshot_repository


class TestTradingTime:
    def test_weekday_within_hours(self):
        assert is_trading_time(datetime(2026, 9, 28, 9, 0)) is True
        assert is_trading_time(datetime(2026, 9, 28, 15, 35)) is True

    def test_weekday_outside_hours(self):
        assert is_trading_time(datetime(2026, 9, 28, 8, 59)) is False
        assert is_trading_time(datetime(2026, 9, 28, 15, 36)) is False

    def test_weekend(self):
        assert is_trading_time(datetime(2026, 9, 26, 10, 0)) is False


class TestComputeDailyReturns:
    def test_empty(self):
        assert compute_daily_returns([]) == []

    def test_single_day_no_previous(self):
        snaps = [(datetime(2026, 9, 28, 9, 31), 100000.0)]
        result = compute_daily_returns(snaps)
        assert result == [{"date": "2026-09-28", "pnl": None, "return": None}]

    def test_two_days(self):
        snaps = [
            (datetime(2026, 9, 25, 14, 0), 100000.0),
            (datetime(2026, 9, 25, 15, 0), 101000.0),
            (datetime(2026, 9, 28, 9, 31), 102000.0),
        ]
        result = compute_daily_returns(snaps)
        assert result[0] == {"date": "2026-09-25", "pnl": None, "return": None}
        assert result[1]["date"] == "2026-09-28"
        assert result[1]["pnl"] == 1000.0
        assert result[1]["return"] == round(1000.0 / 101000.0, 6)


class TestCompoundReturns:
    def test_compound(self):
        assert compound_returns([0.01, 0.02]) == round(1.01 * 1.02 - 1, 6)

    def test_skips_none(self):
        assert compound_returns([None, 0.01, None]) == 0.01

    def test_all_none(self):
        assert compound_returns([None, None]) is None
        assert compound_returns([]) is None


class TestComputeCurve:
    def setup_method(self):
        self.snaps = [
            (datetime(2026, 9, 25, 15, 0), 100000.0),
            (datetime(2026, 9, 28, 9, 31), 100100.0),
            (datetime(2026, 9, 28, 10, 31), 100300.0),
        ]

    def test_day_curve_uses_prior_day_close_as_base(self):
        curve = compute_curve(self.snaps, "day", datetime(2026, 9, 28).date())
        assert [p["t"] for p in curve] == ["2026-09-28 09:31", "2026-09-28 10:31"]
        assert curve[0]["return"] == 0.001
        assert curve[1]["return"] == 0.003
        assert curve[1]["total_asset"] == 100300.0

    def test_day_curve_without_prior_base_first_point_zero(self):
        snaps = self.snaps[1:]
        curve = compute_curve(snaps, "day", datetime(2026, 9, 28).date())
        assert curve[0]["return"] == 0.0
        assert curve[1]["return"] == round(100300.0 / 100100.0 - 1, 6)

    def test_month_curve_daily_points(self):
        curve = compute_curve(self.snaps, "month", datetime(2026, 9, 28).date())
        assert [p["t"] for p in curve] == ["2026-09-25", "2026-09-28"]
        assert curve[0]["return"] == 0.0
        assert curve[1]["return"] == 0.003

    def test_year_curve_daily_points(self):
        curve = compute_curve(self.snaps, "year", datetime(2026, 9, 28).date())
        assert [p["t"] for p in curve] == ["2026-09-25", "2026-09-28"]

    def test_empty_window(self):
        assert compute_curve(self.snaps, "day", datetime(2026, 9, 29).date()) == []
        assert compute_curve([], "day", datetime(2026, 9, 28).date()) == []

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            compute_curve(self.snaps, "week", datetime(2026, 9, 28).date())


class TestComputeMonthlyReturns:
    def setup_method(self):
        # 08-31 为首个有快照日（无基准，pnl/return 为 None）；
        # 09 月两日各 +1%，10-09 再 +1%
        self.snaps = [
            (datetime(2026, 8, 31, 15, 0), 100000.0),
            (datetime(2026, 9, 1, 15, 0), 101000.0),
            (datetime(2026, 9, 28, 15, 0), 102010.0),
            (datetime(2026, 10, 9, 15, 0), 103030.1),
        ]

    def test_monthly_aggregation(self):
        result = compute_monthly_returns(self.snaps, 2026)
        assert [m["month"] for m in result] == ["2026-08", "2026-09", "2026-10"]
        # 08 月仅首日，无基准可计
        assert result[0] == {"month": "2026-08", "pnl": None, "return": None}
        # 09 月：pnl = 1000 + 1010，return = 1.01² - 1
        assert result[1]["pnl"] == 2010.0
        assert result[1]["return"] == round(1.01 * 1.01 - 1, 6)
        # 10 月：单日 +1%
        assert result[2]["pnl"] == 1020.1
        assert result[2]["return"] == 0.01

    def test_months_without_data_absent(self):
        snaps = [
            (datetime(2026, 9, 1, 15, 0), 101000.0),
            (datetime(2026, 10, 9, 15, 0), 102010.0),
        ]
        result = compute_monthly_returns(snaps, 2026)
        assert [m["month"] for m in result] == ["2026-09", "2026-10"]

    def test_year_filter(self):
        assert compute_monthly_returns(self.snaps, 2025) == []

    def test_empty(self):
        assert compute_monthly_returns([], 2026) == []


class TestComputeYearlyReturns:
    def test_yearly_aggregation(self):
        snaps = [
            (datetime(2025, 12, 31, 15, 0), 100000.0),
            (datetime(2026, 1, 5, 15, 0), 101000.0),
            (datetime(2026, 9, 28, 15, 0), 102010.0),
        ]
        result = compute_yearly_returns(snaps)
        assert [y["year"] for y in result] == ["2025", "2026"]
        assert result[0] == {"year": "2025", "pnl": None, "return": None}
        assert result[1]["pnl"] == 2010.0
        assert result[1]["return"] == round(1.01 * 1.01 - 1, 6)

    def test_empty(self):
        assert compute_yearly_returns([]) == []


class TestAssetSnapshotRepository:
    @pytest.fixture(params=["memory", "sqlalchemy"])
    def repo(self, request):
        if request.param == "memory":
            return InMemoryAssetSnapshotRepository()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        return SQLAlchemyAssetSnapshotRepository(Session())

    def test_upsert_same_minute_overwrites(self, repo):
        ts = datetime(2026, 9, 28, 9, 31)
        repo.upsert_snapshot("account", None, ts, 100.0, 50.0, 50.0, 1.0)
        repo.upsert_snapshot("account", None, ts, 200.0, 60.0, 140.0, 2.0)
        rows = repo.list_range("account")
        assert len(rows) == 1
        assert float(rows[0].total_asset) == 200.0
        assert float(rows[0].daily_pnl) == 2.0

    def test_list_range_filters_and_orders(self, repo):
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 10, 0), 3.0, 0, 0, 0)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 9, 0), 1.0, 0, 0, 0)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 9, 30), 2.0, 0, 0, 0)
        repo.upsert_snapshot("strategy", "s1", datetime(2026, 9, 28, 9, 0), 9.0, 0, 0, 0)

        rows = repo.list_range(
            "account", None,
            start=datetime(2026, 9, 28, 9, 0),
            end=datetime(2026, 9, 28, 9, 30),
        )
        assert [float(r.total_asset) for r in rows] == [1.0, 2.0]

        all_rows = repo.list_range("account")
        assert [float(r.total_asset) for r in all_rows] == [1.0, 2.0, 3.0]

    def test_get_latest_before(self, repo):
        repo.upsert_snapshot("account", None, datetime(2026, 9, 25, 15, 0), 100.0, 0, 0, 0)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 9, 31), 101.0, 0, 0, 0)

        latest = repo.get_latest_before("account", None, datetime(2026, 9, 28, 0, 0))
        assert float(latest.total_asset) == 100.0

        assert repo.get_latest_before("account", None, datetime(2026, 9, 25, 0, 0)) is None

    def test_scope_isolation(self, repo):
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 9, 31), 100.0, 0, 0, 0)
        repo.upsert_snapshot("strategy", "s1", datetime(2026, 9, 28, 9, 31), 50.0, 0, 0, 0)
        assert len(repo.list_range("account")) == 1
        assert len(repo.list_range("strategy", "s1")) == 1
        assert repo.list_range("strategy", "s2") == []


class TestPnlOverviewApi:
    def _seed_account_snapshots(self, server):
        repo = _snapshots_repo(server)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 25, 15, 0), 100000.0, 60000.0, 40000.0, 0.0)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 9, 31), 100100.0, 60100.0, 40000.0, 100.0)
        repo.upsert_snapshot("account", None, datetime(2026, 9, 28, 10, 31), 100300.0, 60300.0, 40000.0, 300.0)

    def test_invalid_token_401(self, client):
        response = client.get("/api/pnl/overview", headers={"X-Token": "bad-token"})
        assert response.status_code == 401

    def test_missing_token_422(self, client):
        response = client.get("/api/pnl/overview")
        assert response.status_code == 422

    def test_strategy_scope_requires_strategy_id(self, client, server):
        response = client.get(
            "/api/pnl/overview?scope=strategy",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 400

    def test_invalid_date_400(self, client, server):
        response = client.get(
            "/api/pnl/overview?date=2026/09/28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 400

    def test_invalid_scope_400(self, client, server):
        response = client.get(
            "/api/pnl/overview?scope=bogus",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 400

    def test_strategy_not_found_404(self, client, server):
        response = client.get(
            "/api/pnl/overview?scope=strategy&strategy_id=nonexistent",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 404

    def test_empty_data_200_with_nulls(self, client, server):
        response = client.get(
            "/api/pnl/overview?date=2026-09-28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["scope"] == "account"
        assert data["period"] == "day"
        assert data["date"] == "2026-09-28"
        assert data["summary"] == {
            "total_asset": None,
            "today_pnl": None,
            "cum_return": None,
            "period_return": None,
        }
        assert data["curve"] == []
        assert data["daily_returns"] == []
        assert data["monthly_returns"] is None
        assert data["yearly_returns"] is None

    def test_day_overview_values(self, client, server):
        self._seed_account_snapshots(server)
        response = client.get(
            "/api/pnl/overview?period=day&date=2026-09-28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]

        summary = data["summary"]
        assert summary["total_asset"] == 100300.0
        assert summary["today_pnl"] == 300.0
        assert summary["cum_return"] == 0.003
        assert summary["period_return"] == 0.003

        assert [p["t"] for p in data["curve"]] == ["2026-09-28 09:31", "2026-09-28 10:31"]
        assert data["curve"][0]["return"] == 0.001
        assert data["curve"][1]["total_asset"] == 100300.0

        daily = data["daily_returns"]
        assert [d["date"] for d in daily] == ["2026-09-25", "2026-09-28"]
        assert daily[0]["pnl"] is None
        assert daily[1] == {"date": "2026-09-28", "pnl": 300.0, "return": 0.003}

        # 日视图不做月/年聚合，字段固定为 null 以保持响应结构一致
        assert data["monthly_returns"] is None
        assert data["yearly_returns"] is None

    def test_month_overview_values(self, client, server):
        self._seed_account_snapshots(server)
        response = client.get(
            "/api/pnl/overview?period=month&date=2026-09-28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["period"] == "month"
        assert [p["t"] for p in data["curve"]] == ["2026-09-25", "2026-09-28"]
        assert data["curve"][0]["return"] == 0.0
        assert data["curve"][1]["return"] == 0.003
        assert data["summary"]["period_return"] == 0.003
        assert len(data["daily_returns"]) == 2
        assert data["monthly_returns"] == [
            {"month": "2026-09", "pnl": 300.0, "return": 0.003}
        ]
        assert data["yearly_returns"] is None

    def test_year_overview_values(self, client, server):
        self._seed_account_snapshots(server)
        response = client.get(
            "/api/pnl/overview?period=year&date=2026-09-28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert [p["t"] for p in data["curve"]] == ["2026-09-25", "2026-09-28"]
        assert data["summary"]["period_return"] == 0.003
        assert len(data["daily_returns"]) == 2
        assert data["yearly_returns"] == [
            {"year": "2026", "pnl": 300.0, "return": 0.003}
        ]
        assert data["monthly_returns"] is None

    def test_strategy_scope(self, client, server):
        create_resp = client.post(
            "/api/strategies",
            json={"name": "盈亏策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        sid = create_resp.json()["data"]["id"]
        repo = _snapshots_repo(server)
        repo.upsert_snapshot("strategy", sid, datetime(2026, 9, 25, 15, 0), 100000.0, 100000.0, 0.0, 0.0)
        repo.upsert_snapshot("strategy", sid, datetime(2026, 9, 28, 9, 31), 100500.0, 100500.0, 0.0, 500.0)

        response = client.get(
            f"/api/pnl/overview?scope=strategy&strategy_id={sid}&date=2026-09-28",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["scope"] == "strategy"
        assert data["summary"]["total_asset"] == 100500.0
        assert data["summary"]["today_pnl"] == 500.0
        assert data["summary"]["period_return"] == 0.005


class TestSnapshotLoop:
    async def test_collects_account_snapshot_when_trading_time(self):
        repo = InMemoryAssetSnapshotRepository()
        srv = QMTServer(
            account_id="test_account",
            mini_qmt_path="/tmp/mock_qmt",
            host="127.0.0.1",
            port=8012,
            asset_snapshot_repository=repo,
        )
        try:
            await srv.init_trader_async()
            for _ in range(100):
                if srv.qmt_connected:
                    break
                await asyncio.sleep(0.05)
            assert srv.qmt_connected
            srv.running = True

            with patch("backend.server.is_trading_time", return_value=True):
                task = asyncio.create_task(srv._snapshot_loop())
                for _ in range(100):
                    if repo.list_range("account"):
                        break
                    await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            rows = repo.list_range("account")
            assert len(rows) == 1
            assert rows[0].ts.second == 0
            assert rows[0].ts.microsecond == 0
            assert float(rows[0].total_asset) > 0
        finally:
            srv.running = False
            await srv.stop_async()

    async def test_skips_when_not_trading_time(self):
        repo = InMemoryAssetSnapshotRepository()
        srv = QMTServer(
            account_id="test_account",
            mini_qmt_path="/tmp/mock_qmt",
            host="127.0.0.1",
            port=8013,
            asset_snapshot_repository=repo,
        )
        try:
            await srv.init_trader_async()
            for _ in range(100):
                if srv.qmt_connected:
                    break
                await asyncio.sleep(0.05)
            srv.running = True

            with patch("backend.server.is_trading_time", return_value=False):
                task = asyncio.create_task(srv._snapshot_loop())
                await asyncio.sleep(0.2)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            assert repo.list_range("account") == []
        finally:
            srv.running = False
            await srv.stop_async()

    def test_snapshot_task_created(self):
        srv = QMTServer(
            account_id="test_account",
            mini_qmt_path="/tmp/mock_qmt",
            host="127.0.0.1",
            port=8014,
            asset_snapshot_repository=InMemoryAssetSnapshotRepository(),
        )
        loop, thread = _start_server(srv)
        try:
            assert srv._snapshot_task is not None
            assert not srv._snapshot_task.done()
        finally:
            _stop_server(srv, loop, thread)
