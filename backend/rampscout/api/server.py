"""Production entrypoint: one origin serves the API under /api and the built React app.

Same-origin keeps the demo-session cookie first-party (no SameSite=None needed) and lets
the hosted demo run as a single web service next to the worker.

    uvicorn rampscout.api.server:app
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from rampscout.api.app import create_app

DIST = Path(
    os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist")
)


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes (hash routing makes this rare, but safe)."""

    async def get_response(self, path: str, scope: Scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            return FileResponse(DIST / "index.html")
        return response


def create_server() -> FastAPI:
    root = FastAPI(title="RampScout", docs_url=None, redoc_url=None, openapi_url=None)
    root.mount("/api", create_app())
    if (DIST / "index.html").exists():
        root.mount("/", SPAStaticFiles(directory=DIST, html=True), name="web")
    return root


app = create_server()
