"""
Start / watch / stop auto_match_sofa.py from the dashboard.

The run is a subprocess of the dashboard (one uvicorn process). Mutual exclusion with
the scheduled task and CLI comes from the MySQL named lock taken inside
auto_match_sofa.py, which this module also reads to report runs it did not start.
"""
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "auto_match_sofa.py"
LOG_DIR = REPO_ROOT / "logs"
TAIL_LINES = 80
LOCK_NAME = "pregames_auto_match"

REASON_NO_LOG = "Can't read the RapidAPI call log, so the quota can't be checked."


class SyncConflict(Exception):
    """Maps to HTTP 409."""


class SyncUnavailable(Exception):
    """Maps to HTTP 503."""


_state_lock = threading.Lock()
_current: dict | None = None
_last: dict | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _popen(args, **kw):
    return subprocess.Popen(args, **kw)


def _lock_in_use() -> bool:
    from database import engine

    with engine.connect() as conn:
        return bool(conn.execute(text("SELECT IS_USED_LOCK(:n) IS NOT NULL"), {"n": LOCK_NAME}).scalar())


def _window() -> dict:
    import auto_match_sofa
    from database import engine

    with engine.connect() as conn:
        last_done, start, end = auto_match_sofa.date_window(conn, None)
    dates = 0
    if start is not None and end is not None and end >= start:
        dates = (end - start).days + 1
    iso = lambda v: v.isoformat() if v is not None else None
    return {"last_completed": iso(last_done), "start": iso(start), "end": iso(end), "dates": dates}


def _quota() -> dict:
    from webapi import queries

    return queries.load_api_quota()


def _dates_done_since(ts: datetime) -> int:
    from database import engine

    naive = ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM sofa_match_dates WHERE completed_at >= :ts"),
                                {"ts": naive}).scalar() or 0)


def _reap() -> None:
    global _current, _last
    with _state_lock:
        if _current is not None and _current["proc"].poll() is not None:
            _last = {
                "started_by": _current["started_by"],
                "started_at": _current["started_at"],
                "finished_at": _now(),
                "exit_code": _current["proc"].returncode,
                "log_path": _current["log_path"],
                "stopped": _current.get("stopped", False),
            }
            _current = None


def _tail(path) -> list[str]:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()[-TAIL_LINES:]
    key = ""
    try:
        import batch_match_sofa as bms

        key = getattr(bms, "RAPIDAPI_KEY", "") or ""
    except Exception:
        key = ""
    if key:
        lines = [ln.replace(key, "****") for ln in lines]
    return lines


def _outcome(last: dict) -> str:
    if last.get("stopped"):
        return "stopped"
    code = last["exit_code"]
    if code == 0:
        return "finished"
    if code == 3:
        return "busy"
    return "error"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def status() -> dict:
    _reap()
    with _state_lock:
        cur = dict(_current) if _current else None
        last = dict(_last) if _last else None

    started_here = cur is not None
    running = started_here or _lock_in_use()
    window = _window()
    q = _quota()
    used, limit = q.get("api_calls_used"), q.get("api_call_limit")

    calls_this_run = dates_done = None
    if cur is not None:
        if used is not None and cur.get("calls_at_start") is not None:
            calls_this_run = max(0, used - cur["calls_at_start"])
        dates_done = _dates_done_since(cur["started_at"])

    if running:
        reason = "A run is already in progress."
        if not started_here:
            reason += " It was started outside the dashboard."
    elif used is None:
        reason = REASON_NO_LOG
    elif used >= limit:
        reason = "The RapidAPI limit for this cycle is reached. It resets on the 18th."
    elif window["dates"] == 0:
        reason = "Nothing to do — already caught up."
    else:
        reason = None

    last_out = None
    if last:
        last_out = {
            "started_by": last["started_by"],
            "started_at": _iso(last["started_at"]),
            "finished_at": _iso(last["finished_at"]),
            "exit_code": last["exit_code"],
            "log_path": str(last["log_path"]),
            "outcome": _outcome(last),
        }

    log_path = cur["log_path"] if cur else (last["log_path"] if last else None)
    return {
        "running": running,
        "started_here": started_here,
        "started_by": cur["started_by"] if cur else None,
        "started_at": _iso(cur["started_at"]) if cur else None,
        "calls_this_run": calls_this_run,
        "dates_done_this_run": dates_done,
        "window": window,
        "quota": {"used": used, "limit": limit, "cycle_start": q.get("api_cycle_start")},
        "can_start": reason is None,
        "reason": reason,
        "last_run": last_out,
        "log": _tail(log_path) if log_path else [],
    }


def plan() -> dict:
    import auto_match_sofa
    from database import engine

    window = _window()
    q = _quota()
    rows: list[dict] = []
    if window["dates"] > 0:
        with engine.connect() as conn:
            rows = auto_match_sofa.plan_rows(conn, datetime.fromisoformat(window["start"]).date(),
                                             datetime.fromisoformat(window["end"]).date()) or []
    used, limit = q.get("api_calls_used"), q.get("api_call_limit")
    return {
        "window": window,
        "quota": {"used": used, "limit": limit, "cycle_start": q.get("api_cycle_start")},
        "rows": rows,
        "max_calls_total": sum(r["max_calls"] for r in rows),
        "calls_left": (limit - used) if used is not None and limit is not None else None,
    }


def start(username: str) -> dict:
    global _current
    _reap()
    st = status()
    if not st["can_start"]:
        if st["reason"] == REASON_NO_LOG:
            raise SyncUnavailable(st["reason"])
        raise SyncConflict(st["reason"])

    LOG_DIR.mkdir(exist_ok=True)
    started_at = _now()
    log_path = LOG_DIR / f"sofa_sync_{started_at:%Y%m%d_%H%M%S}.log"
    with open(log_path, "ab") as f:
        proc = _popen([sys.executable, "-u", str(SCRIPT)], cwd=str(REPO_ROOT), stdout=f,
                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    with _state_lock:
        _current = {"proc": proc, "started_at": started_at, "started_by": username,
                    "log_path": log_path, "calls_at_start": st["quota"]["used"], "stopped": False}
    logger.info("[SOFA SYNC] started by %s, log %s", username, log_path)
    return status()


def stop(username: str) -> dict:
    _reap()
    with _state_lock:
        cur = _current
        if cur is not None and cur["proc"].poll() is None:
            cur["stopped"] = True
            cur["proc"].terminate()
            logger.info("[SOFA SYNC] stop requested by %s", username)
            alive = True
        else:
            alive = False
    if alive:
        return status()
    if _lock_in_use():
        raise SyncConflict("This run was started outside the dashboard (e.g. the scheduled task) "
                           "and can't be stopped here.")
    raise SyncConflict("No run is in progress.")
