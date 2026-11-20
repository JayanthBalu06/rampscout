# RampScout — Build Plan (~48 h)

Rule from the brief: **one complete conversion journey before visual polish.** Each phase ends green in CI and is demoable.

## Repo layout

```
rampscout/
  backend/
    rampscout/
      domain/        pricing.py, ranking.py, eligibility.py, clock.py, models.py (pure, mypy --strict)
      providers/     base.py, fixture_a.py, fixture_b.py, registry.py (concurrent fetch w/ timeout)
      agent/         evaluate.py (shared decision fn), execute.py, intent_parser.py (Claude + rules)
      settlement/    signer.py (FakeSigner, Web3Signer), adapter.py, reconcile.py, payout_sim.py
      db/            models.py (SQLAlchemy), session.py, migrations/ (Alembic)
      api/           app.py, routes/{quotes,intents,authorizations,demo,health}.py, schemas.py
      worker/        main.py (poll loop + reconciler)
      logging.py     structlog + redaction
    tests/           test_pricing.py, test_ranking.py, test_watch.py, test_settlement.py, test_api.py, conftest.py
    scripts/         seed.py, demo.py (scripted CLI walkthrough), gen_wallet.py
    pyproject.toml
  frontend/          Vite + React + TS + Tailwind; src/{api,components,pages,lib/money.ts}
  docs/              SPEC.md, PLAN.md, TESTNET_SETUP.md, DEMO_SCRIPT.md, architecture.svg
  docker-compose.yml postgres (+ optional api/worker)
  render.yaml        API, worker, Postgres, static site
  Makefile           up, migrate, seed, test, api, worker, web, demo
  .github/workflows/ci.yml
  .env.example  README.md
```

## Phase 0 — Scaffold (≈2 h)
- [x] git init, Python 3.11 venv, pyproject (fastapi, uvicorn, sqlalchemy, psycopg, alembic, pydantic-settings, web3, anthropic, structlog, pytest, httpx, ruff, mypy)
- [x] docker-compose Postgres 16, Makefile targets, `.env.example`, `.gitignore`
- [x] Vite React TS + Tailwind skeleton, API client with typed money-as-string
- [x] CI workflow: Postgres service, backend lint/type/test, frontend tsc/lint/vitest
**Exit:** `make up && make test` passes an empty suite in CI.

## Phase 1 — Quote comparison (≈5 h)
- [x] `pricing.py`, `ranking.py`, `eligibility.py`, `FixtureClock`/`SystemClock`
- [x] Fixture providers A/B with tick script, fresh id/expiry, chaos hooks (down/timeout)
- [x] `registry.fetch_all()` with `asyncio.gather` + `wait_for` timeout → ok / errors
- [x] DB: sessions, destinations, quote_snapshots; seed script
- [x] `POST /quotes`, `GET /health`, session cookie middleware
- [x] Compare screen (plain styling) with fee breakdown, expiry, ETA in user tz, labels
- [x] Tests Q1–Q7
**Exit:** browser shows B beating A at 600 USDC with exact numbers.

## Phase 2 — Confirmed watches + agent (≈8 h)
- [x] Tables: authorizations, decision_events, notifications, executions (skeleton)
- [x] `POST /authorizations` (idempotency, terms_hash, validation), `GET`, `cancel`, list
- [x] `evaluate_watch()` shared function; worker loop with `FOR UPDATE SKIP LOCKED`
- [x] `/demo/advance` running one synchronous evaluation; `/demo/reset`
- [x] Notify path end-to-end; expiry; cancel conflict
- [x] Intent parser: Claude tool-use with `IntentDraft` schema, ambiguity questions, demo-clock-aware date resolution (server re-resolves `deadline_local` + tz with zoneinfo); rules fallback; `unavailable` without key
- [x] Watch builder + review screen; watch detail with last/next check + reason (plain)
- [x] Tests W1–W8
**Exit:** create 10,000 MXN Notify watch → tick 0 waits → advance → notified. Close browser, reopen, state intact.

## Phase 3 — Settlement (≈10 h)  ← the riskiest phase, start early on day 2
- [x] `Signer` protocol; `FakeSigner` (deterministic hashes, records calls, drop-response chaos)
- [x] Execute: claim → refresh quote → full revalidation → unique execution → advisory lock → sign → persist+commit → broadcast
- [x] Reconciler on worker start and each loop; identical-bytes rebroadcast; Transfer-log verification
- [x] Simulated payout with retry-by-execution-id; `fail_next_payout` chaos
- [x] Immediate "Convert now" path incl. 409 `quote_changed`
- [x] Settlement health check → simulated mode + banner
- [x] Receipt screen
- [x] Tests S1–S7
- [ ] **You:** follow `docs/TESTNET_SETUP.md` (I'll write it in this phase after verifying chain ID 84532, Circle USDC address, explorer, faucets against official docs). Generate the wallet with `scripts/gen_wallet.py`, fund it with ETH + USDC, and create two route recipient wallets.
- [x] `Web3Signer` (built, offline-tested)
- [ ] Live run on Base Sepolia; confirm on explorer (needs funded wallet)
**Exit:** auto watch fires on tick 1, a real Base Sepolia tx is verified, receipt shows hash + simulated payout. Chaos "drop broadcast response" + worker restart reconciles to the same hash.

## Phase 4 — Polish, hosting, handoff (≈10 h)
- [ ] UI pass: route cards with fee waterfall, "higher rate ≠ more pesos" callout, decision timeline, receipt side-by-side, demo control drawer with chaos toggles, settlement banner, dark mode, a11y (labels, focus, contrast, live region for status changes)
- [ ] Claude one-line decision summaries on timeline events (optional, cached)
- [ ] Architecture diagram (SVG) + agent-loop diagram in README
- [ ] README: pitch, real-vs-simulated table, architecture, agent loop & limits, reliability guarantees (each mapped to a test), setup/seed/test/demo commands, env vars, Future section, "later experiment: backtest watch vs immediate"
- [ ] `render.yaml`; deploy; daily onchain cap; smoke test hosted URL
- [ ] `docs/DEMO_SCRIPT.md` (2-min path) + `scripts/demo.py` CLI walkthrough
- [ ] **You:** record 2–3 min video of a real testnet run (captioned for accessibility); make repo public

## Buffer (≈6 h) — Playwright smoke, backtest stub, bug fixes

## Things I need from you, and when
| When | What |
|---|---|
| Phase 2 | `ANTHROPIC_API_KEY` in `.env` (optional; the form works without it) |
| Before Phase 3 live run | Decision on `DEMO_TRANSFER_SCALE` (SPEC §7.1); funded Base Sepolia signer key in `.env`; an RPC URL (public `https://sepolia.base.org` works; Alchemy/QuickNode is more reliable) |
| Phase 4 | Render account (free tier), GitHub repo name/visibility |

## Final report checklist (delivered at the end)
Which flows were actually run (local fake signer, local live testnet, hosted), which integrations used fixtures (providers, payout, MXN conversion), the test results, and any deviations from the spec.
