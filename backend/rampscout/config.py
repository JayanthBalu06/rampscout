"""Runtime configuration. All secrets come from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    database_url: str = "postgresql+psycopg://rampscout:rampscout@localhost:5432/rampscout"
    test_database_url: str = (
        "postgresql+psycopg://rampscout:rampscout@localhost:5432/rampscout_test"
    )
    cors_origins: str = "http://localhost:5173"
    intent_parses_per_hour: int = 30  # per demo session; protects the model API key
    intent_parses_per_hour_global: int = 300
    cookie_secure: bool = False  # true when the UI is served cross-site over HTTPS

    demo_mode: bool = True
    # fixture: each demo session has a manually advanced clock. system: wall clock.
    clock_mode: Literal["fixture", "system"] = "fixture"
    demo_clock_start: datetime = datetime.fromisoformat("2026-11-27T17:00:00+00:00")
    demo_tick_seconds: int = 900
    quote_ttl_seconds: int = 120
    safety_margin_seconds: int = 120
    provider_timeout_ms: int = 1500
    poll_interval_seconds: int = 30
    worker_loop_seconds: float = 2.0
    # Run the worker loop inside the web process (free hosting tiers without workers).
    embedded_worker: bool = False

    # User-approved limits the agent can never exceed.
    max_authorization_usdc: Decimal = Decimal("1000")
    max_watch_days: int = 7

    rpc_url: str = ""
    rpc_send_url: str = ""  # optional: Base recommends a sequencer endpoint for sends
    receipt_wait_seconds: float = 30.0
    expected_chain_id: int = 84532
    usdc_contract: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    signer_private_key: SecretStr = SecretStr("")
    signer_address: str = ""
    route_a_settlement_address: str = ""
    route_b_settlement_address: str = ""
    demo_transfer_scale: Decimal = Decimal("0.01")
    max_onchain_transfer_usdc: Decimal = Decimal("10")
    daily_onchain_runs: int = 20
    # Below this signer balance the app switches to the simulated ledger (one demo transfer).
    min_signer_usdc: Decimal = Decimal("6")
    explorer_tx_url: str = "https://sepolia.basescan.org/tx/"

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-opus-5-5"
    anthropic_timeout_seconds: float = 20.0

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Hosts (Render, Heroku) hand out postgres:// URLs; we use the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
