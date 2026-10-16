"""
Dashboard web app: JSON API under /api plus the built React UI (web/dist).
Run: uvicorn webapi.app:app --host 0.0.0.0 --port 9995
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from webapi import auth, routes

logging.basicConfig(level=logging.INFO)

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the React build: /assets/* as static files, any other non-API path -> index.html."""
    if not (dist / "index.html").is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


def create_app(dist: Path = WEB_DIST) -> FastAPI:
    app = FastAPI(
        title="Pregames Dashboard API",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(routes.router)
    mount_spa(app, dist)   # must be last: its catch-all route would shadow later routes
    return app


app = create_app()
