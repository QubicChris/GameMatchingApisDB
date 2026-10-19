import os

import xlsxwriter

import excel_export

Q = "date_from=2026-05-01&date_to=2026-05-02"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_requires_login(client):
    assert client.get(f"/api/export.xlsx?{Q}").status_code == 401
    assert client.get(f"/api/export/preview?{Q}").status_code == 401


def test_bad_params(authed, monkeypatch):
    assert authed.get("/api/export.xlsx?date_from=2026-5-1&date_to=2026-05-02").status_code == 422

    def boom(*a, **k):
        raise excel_export.ExportRangeError("'from' date is after 'to' date")
    monkeypatch.setattr(excel_export, "build_workbook", boom)
    monkeypatch.setattr(excel_export, "preview", boom)
    r = authed.get("/api/export.xlsx?date_from=2026-05-03&date_to=2026-05-02")
    assert r.status_code == 400
    assert authed.get("/api/export/preview?date_from=2026-05-03&date_to=2026-05-02").status_code == 400


def test_too_large(authed, monkeypatch):
    def boom(*a, **k):
        raise excel_export.ExportTooLarge({"Odds": 600_000})
    monkeypatch.setattr(excel_export, "build_workbook", boom)
    r = authed.get(f"/api/export.xlsx?{Q}")
    assert r.status_code == 413 and "Odds" in r.json()["detail"]


def test_success(authed, monkeypatch):
    seen = {}

    def fake(path, date_from, date_to, include_odds=True, conn=None):
        seen["path"] = path
        wb = xlsxwriter.Workbook(str(path))
        wb.add_worksheet("Summary").write(0, 0, "hi")
        wb.close()
        return {}
    monkeypatch.setattr(excel_export, "build_workbook", fake)
    r = authed.get(f"/api/export.xlsx?{Q}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(XLSX)
    assert "pregames_2026-05-01_to_2026-05-02.xlsx" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"
    assert not os.path.exists(seen["path"])  # temp file cleaned up


def test_preview(authed, monkeypatch):
    stub = {"ok": True, "sheets": [{"name": "Games", "rows": 3}], "too_large": [], "max_rows": 500000}
    monkeypatch.setattr(excel_export, "preview", lambda *a, **k: stub)
    r = authed.get(f"/api/export/preview?{Q}")
    assert r.status_code == 200 and r.json() == stub
