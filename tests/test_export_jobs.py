import os
import time

import pytest
import xlsxwriter

import excel_export
from webapi import export_jobs

Q = {"date_from": "2026-05-01", "date_to": "2026-05-02"}
STUB_PREVIEW = {"ok": True, "sheets": [{"name": "Games", "rows": 100}], "too_large": [], "max_rows": 500000}


@pytest.fixture(autouse=True)
def clean_jobs():
    export_jobs.JOBS.clear()
    export_jobs._previews.clear()
    yield
    for job in list(export_jobs.JOBS.values()):
        job.cancel.set()
    time.sleep(0.05)
    for job in list(export_jobs.JOBS.values()):
        if job.path and os.path.exists(job.path):
            os.unlink(job.path)
    export_jobs.JOBS.clear()
    export_jobs._previews.clear()


def write_tiny_xlsx(path):
    wb = xlsxwriter.Workbook(str(path))
    wb.add_worksheet("Summary").write(0, 0, "hi")
    wb.close()


def install_fake(monkeypatch, steps=4, slow_from=None, record=None, raises=None):
    """Fake build_workbook: reports a few progress steps, then writes a tiny real xlsx."""
    def fake(path, date_from, date_to, include_odds=True, conn=None, filters=None, progress=None):
        if record is not None:
            record.append(path)
        if raises is not None:
            raise raises
        n_steps = 300 if slow_from and date_from == slow_from else steps
        for i in range(n_steps):
            progress("fetching", "Games", min(100, (i + 1) * 100 // n_steps))
            time.sleep(0.01)
        progress("writing", "Games", 100)
        progress("saving", None, 0)
        write_tiny_xlsx(path)
        return {"Games": 100}
    monkeypatch.setattr(excel_export, "build_workbook", fake)
    monkeypatch.setattr(excel_export, "preview", lambda *a, **k: STUB_PREVIEW)


def wait_for(client, job_id, states, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = client.get(f"/api/export/jobs/{job_id}").json()
        if body["state"] in states:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {states}; last {body}")


def test_requires_login(client):
    assert client.post("/api/export/jobs", json=Q).status_code == 401
    assert client.get("/api/export/jobs/abc").status_code == 401


def test_lifecycle(authed, monkeypatch):
    paths = []
    install_fake(monkeypatch, record=paths)
    r = authed.post("/api/export/jobs", json=Q)
    assert r.status_code == 202
    assert r.json()["state"] in ("queued", "running")
    jid = r.json()["id"]
    body = wait_for(authed, jid, ("done",))
    assert body["percent"] == 100 and body["filename"] == "pregames_2026-05-01_to_2026-05-02.xlsx"
    f = authed.get(f"/api/export/jobs/{jid}/file")
    assert f.status_code == 200 and f.content[:2] == b"PK"
    assert authed.get(f"/api/export/jobs/{jid}/file").status_code == 404
    assert not os.path.exists(paths[0])


def test_uses_preview_cache(authed, monkeypatch):
    install_fake(monkeypatch)
    assert authed.get("/api/export/preview", params=Q).status_code == 200

    def no_count(*a, **k):
        pytest.fail("preview must not run again")
    monkeypatch.setattr(excel_export, "preview", no_count)
    jid = authed.post("/api/export/jobs", json=Q).json()["id"]
    assert wait_for(authed, jid, ("done", "error"))["state"] == "done"


def test_cancel(authed, monkeypatch):
    paths = []
    install_fake(monkeypatch, slow_from="2026-05-01", record=paths)
    jid = authed.post("/api/export/jobs", json=Q).json()["id"]
    assert authed.delete(f"/api/export/jobs/{jid}").status_code == 204
    wait_for(authed, jid, ("cancelled",))
    assert authed.get(f"/api/export/jobs/{jid}/file").status_code in (404, 409)
    for p in paths:
        assert not os.path.exists(p)


def test_too_large_error(authed, monkeypatch):
    install_fake(monkeypatch, raises=excel_export.ExportTooLarge({"Odds": 600_001}))
    jid = authed.post("/api/export/jobs", json=Q).json()["id"]
    body = wait_for(authed, jid, ("error",))
    assert body["error_status"] == 413 and "Odds" in body["error"]


def test_unexpected_error_hides_details(authed, monkeypatch):
    paths = []
    install_fake(monkeypatch, raises=RuntimeError("secret detail"), record=paths)
    jid = authed.post("/api/export/jobs", json=Q).json()["id"]
    r = authed.get(f"/api/export/jobs/{jid}")
    body = wait_for(authed, jid, ("error",))
    assert body["error_status"] == 500
    assert "secret detail" not in r.text and "secret detail" not in str(body)
    assert not os.path.exists(paths[0])


def test_validation_is_synchronous(authed, monkeypatch):
    install_fake(monkeypatch)
    assert authed.post("/api/export/jobs", json={**Q, "sheets": ["Nope"]}).status_code == 400
    assert authed.post("/api/export/jobs", json={"date_from": "2026-05-03", "date_to": "2026-05-02"}).status_code == 400
    assert authed.post("/api/export/jobs", json={"date_from": "2026-5-3", "date_to": "2026-05-02"}).status_code == 422
    assert export_jobs.JOBS == {}


def _foreign_job(owner="someone-else", state="running", **kw):
    job = export_jobs.Job(id=kw.pop("id", "foreign" + owner), owner=owner, date_from="2026-05-01",
                          date_to="2026-05-02", include_odds=True, filters=excel_export.NO_FILTERS,
                          state=state, **kw)
    export_jobs.JOBS[job.id] = job
    return job


def test_ownership(authed):
    job = _foreign_job(state="done")
    assert authed.get(f"/api/export/jobs/{job.id}").status_code == 404
    assert authed.delete(f"/api/export/jobs/{job.id}").status_code == 404
    assert authed.get(f"/api/export/jobs/{job.id}/file").status_code == 404
    assert not job.cancel.is_set()


def test_one_job_per_user(authed, monkeypatch):
    install_fake(monkeypatch, slow_from="2026-05-01")
    a = authed.post("/api/export/jobs", json=Q).json()["id"]
    b = authed.post("/api/export/jobs", json={"date_from": "2026-05-03", "date_to": "2026-05-04"}).json()["id"]
    wait_for(authed, a, ("cancelled",))
    assert wait_for(authed, b, ("done",))["state"] == "done"


def test_busy(authed, monkeypatch):
    install_fake(monkeypatch)
    _foreign_job(owner="u1", id="j1")
    _foreign_job(owner="u2", id="j2")
    r = authed.post("/api/export/jobs", json=Q)
    assert r.status_code == 429
    assert "busy" in r.json()["detail"]


def _job(**kw):
    base = dict(id="x", owner="Tester", date_from="a", date_to="b", include_odds=True,
                filters=excel_export.NO_FILTERS)
    base.update(kw)
    return export_jobs.Job(**base)


def test_status_math():
    j = _job(state="running", stage="writing", expected={"Games": 100}, fetched={"Games": 100},
             written={"Games": 50}, started_at=time.monotonic() - 10)
    s = export_jobs.status(j)
    assert s["percent"] == 67.5
    assert s["eta_seconds"] == pytest.approx(5, abs=1)
    j = _job(state="running", stage="counting", started_at=time.monotonic() - 10)
    s = export_jobs.status(j)
    assert s["percent"] == 0 and s["eta_seconds"] is None
    j = _job(state="running", stage="saving", expected={"Games": 100}, started_at=time.monotonic() - 10)
    assert export_jobs.status(j)["percent"] == 90
    j = _job(state="done", stage="done", expected={"Games": 100}, started_at=time.monotonic() - 10,
             finished_at=time.monotonic())
    s = export_jobs.status(j)
    assert s["percent"] == 100 and s["eta_seconds"] is None


def test_ttl_sweep(authed, monkeypatch, tmp_path):
    install_fake(monkeypatch)
    old_file = tmp_path / "old.xlsx"
    write_tiny_xlsx(old_file)
    old = _foreign_job(owner="u1", id="old", state="done", path=str(old_file),
                       finished_at=time.monotonic() - export_jobs.JOB_TTL_SECONDS - 5)
    jid = authed.post("/api/export/jobs", json=Q).json()["id"]
    assert old.id not in export_jobs.JOBS
    assert not old_file.exists()
    wait_for(authed, jid, ("done",))
