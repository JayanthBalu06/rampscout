from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from rampscout.config import get_settings
from rampscout.db.models import DemoSession, Execution, Notification, SimChainTx
from rampscout.db.session import SessionLocal
from rampscout.domain.quotes import Quote
from rampscout.providers.base import QuoteRequest
from rampscout.providers.fixture import MX_SPEI, FixtureProvider, Terms
from rampscout.services.sessions import advance_clock
from rampscout.settlement.chain_settler import ChainSettler
from rampscout.settlement.sim_chain import SIM_ROUTE_RECIPIENTS, SIM_TOKEN, SimulatedChain


def session_id_of(client) -> uuid.UUID:
    return uuid.UUID(client.get("/demo/state").json()["session_id"])


def advance_without_eval(session_id: uuid.UUID, ticks: int = 1) -> None:
    """Move the fixture clock but let the test drive evaluation itself."""
    with SessionLocal() as db:
        s = db.get(DemoSession, session_id)
        for _ in range(ticks):
            advance_clock(db, s, get_settings())
        db.commit()


def count(model, **where) -> int:
    with SessionLocal() as db:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return db.scalar(q) or 0


def executions() -> int:
    return count(Execution)


def notifications() -> int:
    return count(Notification)


class SequenceProvider:
    """Route-B-like provider whose rate changes on every call (to simulate stale quotes)."""

    def __init__(self, rates: list[str], route_id: str = "B") -> None:
        self.rates = list(rates)
        self.calls = 0
        self.provider_id = f"seq-{route_id.lower()}"
        self.route_id = route_id
        self.route_name = f"Route {route_id}"

    async def get_quote(self, req: QuoteRequest) -> Quote:
        rate = self.rates[min(self.calls, len(self.rates) - 1)]
        self.calls += 1
        inner = FixtureProvider(
            provider_id=self.provider_id,
            route_id=self.route_id,
            route_name=self.route_name,
            script={0: Terms(Decimal(rate), Decimal("1"), Decimal("40"), timedelta(minutes=10))},
            supported_rails=frozenset({MX_SPEI}),
            ttl=timedelta(seconds=120),
        )
        return await inner.get_quote(req)


class SpySettler(ChainSettler):
    def __init__(self, chain: SimulatedChain | None = None) -> None:
        super().__init__(
            get_settings(),
            chain or SimulatedChain(),
            mode="simulated",
            token_address=SIM_TOKEN,
            recipients=dict(SIM_ROUTE_RECIPIENTS),
        )
        self.settled: list[uuid.UUID] = []

    def settle(self, execution_id: uuid.UUID) -> None:
        self.settled.append(execution_id)
        super().settle(execution_id)


def onchain_txs() -> int:
    """Distinct signed transfers on the (simulated) ledger = payments attempted."""
    return count(SimChainTx)
