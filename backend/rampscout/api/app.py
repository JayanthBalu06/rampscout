from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from rampscout.api import errors
from rampscout.api.deps import DbSession
from rampscout.api.presenters import settlement_out
from rampscout.api.routes import authorizations, demo, quotes, send
from rampscout.api.schemas import SettlementOut
from rampscout.api.session_dep import CurrentSession
from rampscout.config import get_settings
from rampscout.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="RampScout", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.install(app)
    app.include_router(quotes.router)
    app.include_router(authorizations.router)
    app.include_router(send.router)
    app.include_router(demo.router)

    @app.get("/health")
    def health(db: DbSession) -> dict[str, object]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok", "demo_mode": settings.demo_mode}

    @app.post("/session")
    def ensure_session(session: CurrentSession) -> dict[str, str]:
        """Create (or reuse) the demo session cookie. The UI calls this once before any
        other request, so parallel first requests can't each mint a different session."""
        return {"session_id": str(session.id)}

    @app.get("/health/settlement", response_model=SettlementOut)
    def health_settlement(fresh: bool = False) -> SettlementOut:
        """Live verification of RPC, chain id, token and wallet (cached 60 s)."""
        return settlement_out(get_settings(), fresh=fresh)

    return app


app = create_app()
