"""Serve the packaged operator UI without shadowing API routes."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_BACKEND_EXACT = {"health", "ready", "docs", "redoc", "openapi.json"}


def load_ui_dist(env: Mapping[str, str]) -> Path | None:
    raw = env.get("IAC_AGENT_UI_DIST", "").strip()
    if not raw:
        return None
    dist = Path(raw)
    if not (dist / "index.html").is_file():
        raise FileNotFoundError(f"operator UI index.html is missing under {dist}")
    return dist


def mount_operator_ui(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")

    @app.get("/", response_model=None)
    def operator_ui_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}", response_model=None)
    def operator_ui_fallback(full_path: str) -> FileResponse | JSONResponse:
        if _backend_path(full_path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return FileResponse(index)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


def _backend_path(full_path: str) -> bool:
    if full_path in _BACKEND_EXACT:
        return True
    return full_path == "api" or full_path.startswith("api/")
