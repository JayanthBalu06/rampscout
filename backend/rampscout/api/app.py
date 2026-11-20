from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from rampscout.api.deps import DbSession
from rampscout.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="RampScout", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(db: DbSession) -> dict[str, object]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "demo_mode": settings.demo_mode}

    return app


app = create_app()
