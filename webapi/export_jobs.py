"""
Background Excel export jobs with progress, for the dashboard API.

Jobs live in this process's memory: the dashboard must run as ONE uvicorn
process (no --workers). Jobs are lost on restart. Files are temp files that are
deleted after download, on cancel/error, or after JOB_TTL_SECONDS.
"""
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

import excel_export

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 30 * 60
MAX_RUNNING_JOBS = 2
PREVIEW_TTL_SECONDS = 15 * 60

_lock = threading.Lock()


class ExportBusy(Exception):
    """Too many exports are running at once."""


# ── Preview cache: lets a job know the expected row counts without counting again ──

_previews: dict = {}


def remember_preview(key, counts: dict) -> None:
    with _lock:
        _previews[key] = (time.monotonic(), dict(counts))


def cached_counts(key) -> dict | None:
    with _lock:
        hit = _previews.get(key)
        if hit is None:
            return None
        saved_at, counts = hit
        if time.monotonic() - saved_at > PREVIEW_TTL_SECONDS:
            del _previews[key]
            return None
        return dict(counts)


# ── Jobs ─────────────────────────────────────────────────────────────────────

@dataclass
class Job:
    id: str
    owner: str
    date_from: str
    date_to: str
    include_odds: bool
    filters: excel_export.ExportFilters
    state: str = "queued"          # queued | running | done | error | cancelled
    stage: str = "queued"          # queued | counting | fetching | writing | saving | done
    sheet: str | None = None
    expected: dict = field(default_factory=dict)
    fetched: dict = field(default_factory=dict)
    written: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    path: str | None = None
    filename: str = ""
    error: str | None = None
    error_status: int | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


JOBS: dict[str, Job] = {}


def _spawn(target) -> None:
    threading.Thread(target=target, daemon=True, name="export-job").start()


def _remove_file(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _sweep() -> None:
    now = time.monotonic()
    stale = []
    with _lock:
        for jid, job in list(JOBS.items()):
            if job.finished_at is not None and now - job.finished_at > JOB_TTL_SECONDS:
                stale.append(JOBS.pop(jid))
    for job in stale:
        _remove_file(job.path)


def start_job(owner: str, date_from: str, date_to: str, include_odds: bool,
              filters: excel_export.ExportFilters) -> Job:
    _sweep()
    # Validate synchronously so bad input is a 400 right away.
    excel_export.parse_range(date_from, date_to)
    excel_export.sheet_specs(include_odds, filters.sheets)
    with _lock:
        # One running export per user: a new click replaces the old one.
        for other in JOBS.values():
            if other.owner == owner and other.state in ("queued", "running"):
                other.cancel.set()
        active_others = sum(1 for j in JOBS.values()
                            if j.owner != owner and j.state in ("queued", "running"))
        if active_others >= MAX_RUNNING_JOBS:
            raise ExportBusy("The server is busy with other exports. Try again in a minute.")
        job = Job(id=uuid.uuid4().hex, owner=owner, date_from=date_from, date_to=date_to,
                  include_odds=include_odds, filters=filters,
                  filename=excel_export.default_filename(date_from, date_to, include_odds,
                                                         filtered=filters.narrows_rows))
        JOBS[job.id] = job
    _spawn(lambda: _run(job))
    return job


def _finish(job: Job, state: str, **fields) -> None:
    with _lock:
        job.state = state
        job.finished_at = time.monotonic()
        for k, v in fields.items():
            setattr(job, k, v)


def _run(job: Job) -> None:
    with _lock:
        if job.state != "queued":      # cancelled before it started
            return
        job.state = "running"
        job.started_at = time.monotonic()
    path = None
    try:
        key = (job.date_from, job.date_to, job.include_odds, job.filters)
        counts = cached_counts(key)
        if counts is None:
            with _lock:
                job.stage = "counting"
            result = excel_export.preview(job.date_from, job.date_to, job.include_odds, filters=job.filters)
            counts = {s["name"]: s["rows"] for s in result["sheets"]}
            if result["too_large"]:
                raise excel_export.ExportTooLarge({n: counts[n] for n in result["too_large"]})
        with _lock:
            job.expected = counts
        if job.cancel.is_set():
            raise excel_export.ExportCancelled()

        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)

        def cb(stage: str, sheet: str | None, n: int) -> None:
            if job.cancel.is_set():
                raise excel_export.ExportCancelled()
            with _lock:
                job.stage = stage
                job.sheet = sheet
                if stage == "fetching":
                    job.fetched[sheet] = n
                elif stage == "writing":
                    job.written[sheet] = n

        excel_export.build_workbook(path, job.date_from, job.date_to, job.include_odds,
                                    filters=job.filters, progress=cb)
        _finish(job, "done", stage="done", sheet=None, path=path)
    except excel_export.ExportCancelled:
        _remove_file(path)
        _finish(job, "cancelled")
    except excel_export.ExportTooLarge as e:
        _remove_file(path)
        _finish(job, "error", error=str(e), error_status=413)
    except Exception:
        logger.exception("Export job %s failed", job.id)
        _remove_file(path)
        _finish(job, "error", error="Export failed. Check the server log.", error_status=500)


def status(job: Job) -> dict:
    with _lock:
        now = time.monotonic()
        total = 2 * sum(job.expected.values())     # fetch + write units
        done_units = sum(job.fetched.values()) + sum(job.written.values())
        if job.state == "done":
            percent = 100.0
        elif job.stage in ("queued", "counting") or total == 0:
            percent = 0.0 if job.stage != "saving" else 90.0
        elif job.stage == "saving":
            percent = 90.0
        else:
            percent = min(89.0, 90.0 * done_units / total)
        elapsed = ((job.finished_at or now) - job.started_at) if job.started_at else 0.0
        eta = None
        if job.state == "running" and job.stage in ("fetching", "writing", "saving") \
                and percent >= 3 and elapsed >= 2:
            eta = max(0.0, elapsed * (100 - percent) / percent)
        return {
            "id": job.id, "state": job.state, "stage": job.stage, "sheet": job.sheet,
            "percent": round(percent, 1),
            "eta_seconds": round(eta) if eta is not None else None,
            "elapsed_seconds": round(elapsed, 1),
            "error": job.error, "error_status": job.error_status,
            "filename": job.filename if job.state == "done" else None,
        }


def get_job(job_id: str, owner: str) -> Job:
    """Raises KeyError if the job is missing or belongs to someone else."""
    with _lock:
        job = JOBS.get(job_id)
        if job is None or job.owner != owner:
            raise KeyError(job_id)
        return job


def cancel_job(job_id: str, owner: str) -> None:
    job = get_job(job_id, owner)
    job.cancel.set()
    with _lock:
        if job.state == "queued":
            job.state = "cancelled"
            job.finished_at = time.monotonic()


def take_file(job_id: str, owner: str) -> tuple[str, str]:
    """Hand over the finished file (the caller deletes it after sending). Raises KeyError / ValueError."""
    get_job(job_id, owner)
    with _lock:
        job = JOBS.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state != "done" or not job.path:
            raise ValueError("Export is not ready")
        del JOBS[job_id]
        return job.path, job.filename
