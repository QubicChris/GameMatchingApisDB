import sys
import types
from datetime import datetime

import pytest

from webapi import queries

GAME = {"id": 123, "kickoff": "2026-05-16T15:00:00", "_kickoff_dt": datetime(2026, 5, 16, 15, 0),
        "home_team": "A", "away_team": "B", "sofa_event_id": 55, "bookmakers": []}


def test_games_needs_date_or_q(authed):
    assert authed.get("/api/games").status_code == 400


def test_games_passes_args(authed, monkeypatch):
    seen = []
    monkeypatch.setattr(queries, "load_games", lambda *a, **k: seen.append(a) or [])
    r = authed.get("/api/games?date=2026-05-16")
    assert r.status_code == 200
    assert seen == [("2026-05-16", None, "all", None)]


def test_games_validation(authed):
    assert authed.get("/api/games?date=16-05-2026").status_code == 422
    assert authed.get("/api/games?date=2026-05-16&sofa=bogus").status_code == 422
    assert authed.get("/api/games?q=a").status_code == 422


def test_game_404_and_strip_private(authed, monkeypatch):
    monkeypatch.setattr(queries, "load_game", lambda gid: None)
    assert authed.get("/api/games/123").status_code == 404
    monkeypatch.setattr(queries, "load_game", lambda gid: dict(GAME))
    r = authed.get("/api/games/123")
    assert r.status_code == 200
    assert "_kickoff_dt" not in r.json()
    assert r.json()["id"] == 123


def test_blown_leads_bounds(authed, monkeypatch):
    seen = []
    monkeypatch.setattr(queries, "load_blown_leads", lambda n: seen.append(n) or [])
    assert authed.get("/api/blown-leads?min_lead=6").status_code == 422
    assert authed.get("/api/blown-leads?min_lead=3").status_code == 200
    assert seen == [3]


def test_summary_merges(authed, monkeypatch):
    monkeypatch.setattr(queries, "load_summary", lambda: {"total_games": 1})
    monkeypatch.setattr(queries, "load_api_quota", lambda: {"api_calls_used": None})
    assert authed.get("/api/summary").json() == {"total_games": 1, "api_calls_used": None}


def test_fetch_unmatched_game_409(authed, monkeypatch):
    monkeypatch.setattr(queries, "load_game", lambda gid: {**GAME, "sofa_event_id": None})
    assert authed.post("/api/games/123/statistics/fetch").status_code == 409


def _fake_bms(**over):
    base = dict(RAPIDAPI_KEY="k", MONTHLY_CALL_LIMIT=10,
                get_billing_cycle_start=lambda: None, get_cycle_call_count=lambda s: 10,
                fetch_sofa_statistics=lambda sid: pytest.fail("must not call API"),
                store_statistics=lambda *a: None)
    base.update(over)
    return types.SimpleNamespace(**base)


def test_fetch_quota_and_key_guards(authed, monkeypatch):
    monkeypatch.setattr(queries, "load_game", lambda gid: dict(GAME))
    monkeypatch.setitem(sys.modules, "batch_match_sofa", _fake_bms())
    assert authed.post("/api/games/123/statistics/fetch").status_code == 429
    monkeypatch.setitem(sys.modules, "batch_match_sofa", _fake_bms(get_cycle_call_count=lambda s: -1))
    assert authed.post("/api/games/123/statistics/fetch").status_code == 503
    monkeypatch.setitem(sys.modules, "batch_match_sofa", _fake_bms(RAPIDAPI_KEY=""))
    assert authed.post("/api/games/123/statistics/fetch").status_code == 503


def test_fetch_success_stores(authed, monkeypatch):
    stored = []
    monkeypatch.setattr(queries, "load_game", lambda gid: dict(GAME))
    monkeypatch.setattr(queries, "load_statistics", lambda gid: {"periods": ["ALL"], "stats": {}})
    monkeypatch.setitem(sys.modules, "batch_match_sofa", _fake_bms(
        get_cycle_call_count=lambda s: 1,
        fetch_sofa_statistics=lambda sid: [{"period": "ALL"}],
        store_statistics=lambda *a: stored.append(a)))
    r = authed.post("/api/games/123/statistics/fetch")
    assert r.status_code == 200
    assert stored == [(123, 55, [{"period": "ALL"}], "2026-05-16")]
