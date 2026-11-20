# RampScout

> Rates lie, payouts don't. RampScout compares USDC → MXN off-ramp routes by the pesos that actually land in the bank, and an AI agent can watch for your target under limits you approve.

**Status:** hackathon prototype under construction. See [`docs/SPEC.md`](docs/SPEC.md) and [`docs/PLAN.md`](docs/PLAN.md).

## Quick start

Requires Docker, Python 3.11, and Node 20+.

```bash
make setup     # venv + npm install + .env from .env.example
make up        # Postgres in Docker + migrations (dev and test DBs)
make test      # backend (pytest against Postgres) + frontend (vitest)
make api       # FastAPI on :8000
make web       # React app on :5173 (proxies /api to :8000)
```

The full README (architecture, agent loop and limits, real vs. simulated, demo script) arrives in Phase 4.
