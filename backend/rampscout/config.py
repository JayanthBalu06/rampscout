"""Runtime configuration. All secrets come from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, extra="ignore")

    database_url: str = "postgresql+psycopg://rampscout:rampscout@localhost:5432/rampscout"
    test_database_url: str = (
        "postgresql+psycopg://rampscout:rampscout@localhost:5432/rampscout_test"
    )
    cors_origins: str = "http://localhost:5173"

    demo_mode: bool = True
    demo_clock_start: datetime = datetime.fromisoformat("2026-11-27T17:00:00+00:00")
    demo_tick_seconds: int = 900
    quote_ttl_seconds: int = 120
    safety_margin_seconds: int = 120
    provider_timeout_ms: int = 1500
    poll_interval_seconds: int = 30

    rpc_url: str = ""
    expected_chain_id: int = 84532
    usdc_contract: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    signer_private_key: SecretStr = SecretStr("")
    signer_address: str = ""
    route_a_settlement_address: str = ""
    route_b_settlement_address: str = ""
    demo_transfer_scale: Decimal = Decimal("0.01")
    max_onchain_transfer_usdc: Decimal = Decimal("10")
    daily_onchain_runs: int = 20
    explorer_tx_url: str = "https://sepolia.basescan.org/tx/"

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-haiku-5-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
