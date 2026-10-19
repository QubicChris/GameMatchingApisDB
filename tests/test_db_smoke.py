import os

import pytest

pytestmark = [pytest.mark.db, pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1")]


def test_all_queries():
    from webapi import queries as q

    f = q.load_filters()
    assert isinstance(f["dates"], list) and isinstance(f["countries"], list) and isinstance(f["bookmakers"], list)
    assert isinstance(q.load_games(date=f["dates"][0], country=None, sofa="all", q=None), list)
    assert isinstance(q.load_games(date=None, country=None, sofa="matched", q="se"), list)

    games = q.load_games(date=f["dates"][0], country=None, sofa="all", q=None)
    gid = games[0]["id"]
    assert isinstance(q.load_game(gid), dict)
    assert q.load_game(-1) is None
    odds = q.load_odds(gid)
    assert isinstance(odds["bookmakers"], list) and isinstance(odds["markets"], list)
    stats = q.load_statistics(gid)
    assert isinstance(stats["periods"], list) and isinstance(stats["stats"], dict)
    assert isinstance(q.load_incidents(gid), list)

    assert isinstance(q.load_blown_leads(2), list)
    for s in ("", "a"):
        al = q.load_aliases(s)
        assert isinstance(al["sources"], list) and isinstance(al["rows"], list)
    assert isinstance(q.load_market_types(), list)
    mr = q.load_match_rates()
    assert isinstance(mr["countries"], list) and isinstance(mr["leagues"], list)
    assert isinstance(q.load_summary(), dict)
    assert isinstance(q.load_daily_counts(30), list)


def test_api_quota():
    from webapi import queries as q

    quota = q.load_api_quota()
    assert isinstance(quota, dict)
    assert quota["api_calls_used"] is None or isinstance(quota["api_calls_used"], int)


def test_export_preview_and_build(tmp_path):
    import openpyxl

    import excel_export
    from webapi import queries as q

    d = q.load_filters()["dates"][0]
    p = excel_export.preview(d, d)
    assert p["ok"] is True
    out = tmp_path / "x.xlsx"
    excel_export.build_workbook(out, d, d)
    assert out.exists()
    assert "Games" in openpyxl.load_workbook(out).sheetnames
