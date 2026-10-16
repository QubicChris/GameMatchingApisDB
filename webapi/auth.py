"""
Cookie-based auth for the dashboard API, using the users in auth.yaml
(the same file the Streamlit dashboard used; passwords are bcrypt hashes).
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

COOKIE_NAME = "pregames_session"
MAX_FAILURES = 10
LOCKOUT_SECONDS = 15 * 60

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _auth_file() -> Path:
    default = Path(__file__).resolve().parent.parent / "auth.yaml"
    return Path(os.getenv("DASHBOARD_AUTH_FILE", default))


def _config() -> dict:
    with open(_auth_file(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _users() -> dict[str, dict]:
    """Usernames lower-cased -> {"username": original, "name": ..., "password": hash}."""
    users = _config()["credentials"]["usernames"] or {}
    return {u.lower(): {"username": u, **v} for u, v in users.items()}


def _secret() -> str:
    return os.getenv("DASHBOARD_SECRET") or _config()["cookie"]["key"]


def _expiry_days() -> int:
    return int(_config().get("cookie", {}).get("expiry_days", 30))


def _cookie_secure() -> bool:
    return os.getenv("DASHBOARD_COOKIE_SECURE", "false").lower() == "true"


# ── Failed-login lockout (in-memory, per IP) ─────────────────────────────────

def _too_many_failures(ip: str) -> bool:
    with _failures_lock:
        cutoff = time.time() - LOCKOUT_SECONDS
        recent = [t for t in _failures.get(ip, []) if t > cutoff]
        _failures[ip] = recent
        return len(recent) >= MAX_FAILURES


def _record_failure(ip: str) -> None:
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str) -> None:
    with _failures_lock:
        _failures.pop(ip, None)


# ── Session dependency ───────────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Not authenticated")
    user = _users().get(str(payload.get("sub", "")))
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return {"username": user["username"], "name": user.get("name") or user["username"]}


# ── Routes ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    if _too_many_failures(ip):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")

    key = body.username.strip().lower()
    user = _users().get(key)
    ok = False
    if user is not None:
        try:
            ok = bcrypt.checkpw(body.password.encode("utf-8"), str(user["password"]).encode("utf-8"))
        except (ValueError, KeyError):
            ok = False
    if not ok:
        _record_failure(ip)
        logger.warning("[AUTH] failed login for %r from %s", body.username, ip)
        raise HTTPException(401, "Incorrect username or password.")

    _clear_failures(ip)
    days = _expiry_days()
    token = jwt.encode(
        {"sub": key, "exp": datetime.now(timezone.utc) + timedelta(days=days)},
        _secret(),
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE_NAME, token, max_age=days * 86400, httponly=True,
        samesite="lax", secure=_cookie_secure(), path="/",
    )
    return {"username": user["username"], "name": user.get("name") or user["username"]}


@router.post("/logout", status_code=204)
def logout():
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/me")
def me(request: Request):
    return current_user(request)
