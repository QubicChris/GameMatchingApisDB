import sys
import types
from datetime import date
from pathlib import Path

import pytest

import auto_match_sofa
import batch_match_sofa as bms
from webapi import sofa_sync

WINDOW = {"last_completed": "2026-05-15", "start": "2026-05-16", "end": "2026-05-18", "dates": 3}


class FakeProc:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    sofa_sync._current = None
    sofa_sync._last = None
    state = {"lock": False, "window": dict(WINDOW), "quota": {"api_calls_used": 100, "api_call_limit": 9990,
                                                              "api_cycle_start": "2026-05-18"},
             "calls": [], "proc": FakeProc()}
    monkeypatch.setattr(sofa_sync, "_lock_in_use", lambda: state["lock"])
    monkeypatch.setattr(sofa_sync, "_window", lambda: state["window"])
    monkeypatch.setattr(sofa_sync, "_quota", lambda: state["quota"])
    monkeypatch.setattr(sofa_sync, "_dates_done_since", lambda ts: 0)
    monkeypatch.setattr(sofa_sync, "LOG_DIR", tmp_path / "logs")

    def fake_popen(args, **kw):
        state["calls"].append((args, kw))
        kw["stdout"].write(b"started\n")
        return state["proc"]

    monkeypatch.setattr(sofa_sync, "_popen", fake_popen)
    yield state
    sofa_sync._current = None
    sofa_sync._last = None


def test_status_idle(authed):
    body = authed.get("/api/sofa-sync").json()
    assert body["can_start"] is True and body["running"] is False and body["log"] == []
    assert body["reason"] is None and body["last_run"] is None


def test_start_runs_script(authed, fake_env):
    r = authed.post("/api/sofa-sync/start")
    assert r.status_code == 202
    args, kw = fake_env["calls"][0]
    assert args[:2] == [sys.executable, "-u"] and args[2].endswith("auto_match_sofa.py")
    assert Path(kw["cwd"]) == Path(sofa_sync.REPO_ROOT)
    body = authed.get("/api/sofa-sync").json()
    assert body["running"] and body["started_here"] and body["started_by"] == "Tester"
    assert body["log"] == ["started"]


def test_second_start_conflicts(authed):
    assert authed.post("/api/sofa-sync/start").status_code == 202
    r = authed.post("/api/sofa-sync/start")
    assert r.status_code == 409 and "already in progress" in r.json()["detail"]


def test_run_started_outside(authed, fake_env):
    fake_env["lock"] = True
    body = authed.get("/api/sofa-sync").json()
    assert body["running"] and not body["started_here"]
    assert "outside the dashboard" in body["reason"]
    r = authed.post("/api/sofa-sync/stop")
    assert r.status_code == 409 and "started outside" in r.json()["detail"]
    assert authed.post("/api/sofa-sync/start").status_code == 409
    assert fake_env["calls"] == []


def test_quota_guards(authed, fake_env):
    fake_env["quota"]["api_calls_used"] = None
    assert authed.post("/api/sofa-sync/start").status_code == 503
    fake_env["quota"]["api_calls_used"] = 9990
    r = authed.post("/api/sofa-sync/start")
    assert r.status_code == 409 and "limit" in r.json()["detail"]
    assert fake_env["calls"] == []


def test_nothing_to_do(authed, fake_env):
    fake_env["window"] = {"last_completed": None, "start": None, "end": None, "dates": 0}
    r = authed.post("/api/sofa-sync/start")
    assert r.status_code == 409 and "Nothing to do" in r.json()["detail"]


def test_stop_own_run(authed, fake_env):
    authed.post("/api/sofa-sync/start")
    r = authed.post("/api/sofa-sync/stop")
    assert r.status_code == 200 and fake_env["proc"].terminated
    fake_env["proc"].returncode = 1
    body = authed.get("/api/sofa-sync").json()
    assert body["running"] is False
    assert body["last_run"]["outcome"] == "stopped"
    assert authed.post("/api/sofa-sync/stop").status_code == 409


@pytest.mark.parametrize("code,outcome", [(0, "finished"), (3, "busy"), (1, "error")])
def test_outcomes(authed, fake_env, code, outcome):
    authed.post("/api/sofa-sync/start")
    fake_env["proc"].returncode = code
    assert authed.get("/api/sofa-sync").json()["last_run"]["outcome"] == outcome


def test_log_tail_masks_key(authed, monkeypatch, tmp_path):
    log = tmp_path / "x.log"
    lines = [f"line {i}" for i in range(200)]
    lines[150] = "header X-Key: SECRETKEY123 end"
    log.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "batch_match_sofa", types.SimpleNamespace(RAPIDAPI_KEY="SECRETKEY123"))
    out = sofa_sync._tail(log)
    assert len(out) == 80
    assert not any("SECRETKEY123" in ln for ln in out)
    assert any("****" in ln for ln in out)


def test_requires_login(client):
    assert client.get("/api/sofa-sync").status_code == 401
    assert client.get("/api/sofa-sync/plan").status_code == 401
    assert client.post("/api/sofa-sync/start").status_code == 401
    assert client.post("/api/sofa-sync/stop").status_code == 401


def test_plan_totals(monkeypatch):
    rows = [{"date": "2026-05-16", "games": 5, "to_match": 2, "countries": 1, "max_calls": 7},
            {"date": "2026-05-17", "games": 9, "to_match": 4, "countries": 2, "max_calls": 14}]
    monkeypatch.setattr(auto_match_sofa, "plan_rows", lambda conn, s, e: rows)
    monkeypatch.setattr("database.engine", types.SimpleNamespace(connect=lambda: _Ctx()))
    out = sofa_sync.plan()
    assert out["max_calls_total"] == 21 and out["calls_left"] == 9890 and out["rows"] == rows


class _Ctx:
    def __enter__(self):
        return object()

    def __exit__(self, *a):
        return False


def test_plan_rows_arithmetic(monkeypatch):
    monkeypatch.setattr(bms, "CATEGORY_MAP", {"Spain": 1, "Italy": 2})
    R = types.SimpleNamespace
    d1, d2 = date(2026, 5, 16), date(2026, 5, 17)
    fetched = [R(d=d1, country="Spain", games=5, unmatched=2), R(d=d1, country="Italy", games=3, unmatched=1),
               R(d=d1, country="Atlantis", games=4, unmatched=4), R(d=d2, country="Spain", games=2, unmatched=0)]

    class Conn:
        def execute(self, *a, **k):
            return R(fetchall=lambda: fetched)

    rows = auto_match_sofa.plan_rows(Conn(), d1, d2)
    assert rows == [
        {"date": "2026-05-16", "games": 12, "to_match": 3, "countries": 2, "max_calls": 11},
        {"date": "2026-05-17", "games": 2, "to_match": 0, "countries": 0, "max_calls": 0},
    ]
