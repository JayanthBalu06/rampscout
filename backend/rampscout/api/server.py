"""Production entrypoint: one origin serves the API under /api and the built React app.

Same-origin keeps the demo-session cookie first-party (no SameSite=None needed) and lets
the hosted demo run as a single web service next to the worker.

    uvicorn rampscout.api.server:app
"""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from rampscout.api.app import create_app
from rampscout.config import get_settings

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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """With EMBEDDED_WORKER=true the worker loop runs on a daemon thread in this process
    (single-service free hosting). Claims are row-locked, so a separate worker can still
    run alongside it safely."""
    stop = threading.Event()
    if get_settings().embedded_worker:
        from rampscout.worker.main import run_forever

        threading.Thread(
            target=run_forever, args=(lambda: not stop.is_set(),), daemon=True, name="worker"
        ).start()
    yield
    stop.set()


def create_server() -> FastAPI:
    root = FastAPI(
        title="RampScout", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    root.mount("/api", create_app())
    if (DIST / "index.html").exists():
        root.mount("/", SPAStaticFiles(directory=DIST, html=True), name="web")
    return root


app = create_server()
