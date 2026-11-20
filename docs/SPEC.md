# RampScout — Technical Specification

Status: draft v1 (2026-11-20) · Build window: ~48 h · Owner: demo user `freelancer@demo`

## 1. Product summary

RampScout compares off-ramp routes from **USDC → MXN** by what the recipient actually receives after all fees, not by headline exchange rate. A user can **convert now** at the best current quote or **authorize an agent** to watch for a target payout before a deadline. Waiting is optional and may produce a worse quote or no fill. The agent never converts below the confirmed target.

**Pitch in one line:** *"Rates lie, payouts don't. RampScout's agent waits for the payout you asked for, and it can't spend a cent you didn't authorize."*

### 1.1 What is real vs. simulated (must appear in the quote view, receipt, and README)

| Layer | Prototype | Label in UI |
|---|---|---|
| Quote providers A and B | Synthetic fixtures with deterministic tick script | `Synthetic quote` |
| Exchange-rate / spread | Fixture | `Synthetic` |
| USDC transfer to route's settlement wallet | **Real ERC-20 transfer on Base Sepolia** (when signer + RPC configured) | `Testnet · verified onchain` + explorer link |
| USDC transfer when signer/RPC missing | Fake signer, deterministic fake hash | `Simulated settlement` |
| Provider fee deduction, MXN conversion, SPEI bank deposit | Simulated | `Simulated payout` |
| Natural-language parsing | Claude API (optional; form fallback) | `AI draft — review before confirming` |
| Network gas | Paid by demo wallet | `Gas: demo-sponsored` (shown separately, not in net MXN) |

### 1.2 Out of scope (documented as "Future" in README, never mixed into prototype claims)
MXN→USDC direction, other chains, real provider APIs (Bitso, etc.), user-paid gas (design hook exists: `gas_cost_usdc` in ranking, currently 0), multi-user auth, KYC, real SPEI.

## 2. Decisions locked from Q&A

| Topic | Decision |
|---|---|
| Stack | FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16 · Python worker process · React 18 + TypeScript + Vite + Tailwind · web3.py for chain |
| LLM | Claude API, tool-use with a strict JSON schema → `IntentDraft`. Model from env `ANTHROPIC_MODEL` (default `claude-haiku-5-5` for speed; `claude-sonnet-5-5` acceptable). Form-only path works with no key. |
| Testnet | Base Sepolia. Build against fake signer first; `docs/TESTNET_SETUP.md` walks wallet creation, faucets, RPC. |
| Hosting | Render blueprint: API web service, worker background service, Postgres, static frontend. |
| Extras | Reliability "chaos" controls, decision timeline UI, architecture diagram, GitHub Actions CI with Postgres service. |

## 3. Domain model and math

### 3.1 Quote math (single function, `rampscout/domain/pricing.py`)

```
net_mxn = floor_to_centavos( (input_usdc − usdc_fee − gas_cost_usdc) × rate_mxn_per_usdc − mxn_withdrawal_fee )
```
- `decimal.Decimal` everywhere with a module-level context (prec 28). Round **once** at the end, `ROUND_DOWN` to `0.01`.
- `gas_cost_usdc = 0` for the prototype (demo-sponsored), but the term exists so user-paid gas changes ranking with no refactor.
- JSON: all money fields are **strings** (`"9993.25"`). Pydantic models use `Decimal` with a custom serializer; inbound validation rejects floats for money fields.
- Validation: `input_usdc > 0`, at most 6 decimals (USDC precision); `min_payout_mxn > 0`, at most 2 decimals.

### 3.2 Fixture scenario (600 USDC)

| Tick | Route | Rate | USDC fee | MXN fee | Net MXN | ETA |
|---|---|---|---|---|---|---|
| 0 | A | 16.85 | 2 | 100 | **9976.30** | 20 min |
| 0 | B | 16.75 | 1 | 40 | **9993.25** | 10 min |
| 1 | A | 16.85 | 2 | 100 | 9976.30 | 20 min |
| 1 | B | 16.80 | 1 | 40 | **10023.20** | 10 min |
| ≥2 | — | holds tick-1 terms | | | | |

Every fetch generates a fresh `quote_id` (UUIDv4) and `expires_at = clock.now() + QUOTE_TTL` (default 120 s of demo time).

### 3.3 Demo clock

- `Clock` interface: `SystemClock` (production polling) and `FixtureClock` (per demo session, persisted in `demo_sessions.clock_now` + `tick`).
- Fixture start: **Friday 2026-11-27 11:00 America/Mexico_City (17:00 UTC)**, configurable via `DEMO_CLOCK_START`. Each `/demo/advance` adds `DEMO_TICK_SECONDS` (default 15 min) and increments `tick`.
- "Friday at 5 p.m. Mexico City time" therefore resolves to **2026-11-27 17:00 America/Mexico_City = 2026-11-27 23:00 UTC**: six hours of headroom. Mexico has no DST since 2022, so the offset is UTC−6. Resolution uses `zoneinfo`, never hard-coded offsets.
- The **same** `evaluate_watch(auth, clock, providers)` function runs from `/demo/advance` and from the poller. Only the clock differs.

### 3.4 Destination binding

`destinations` row: `alias="My BBVA account"`, masked CLABE `•••• 4821`, currency MXN, supported by routes A and B. Each route has a **server-configured** `settlement_address` (env `ROUTE_A_SETTLEMENT_ADDRESS`, `ROUTE_B_SETTLEMENT_ADDRESS`). No API field, LLM output, or client payload can carry an address used for signing. The settlement adapter looks up the address only from `route_id`.

## 4. Persistence (PostgreSQL)

All timestamps are `timestamptz` stored in UTC. The user's IANA tz is kept on the authorization for display.

| Table | Key columns / constraints |
|---|---|
| `demo_sessions` | `id`, `owner_id`, `clock_now`, `tick`, `chaos_flags jsonb` |
| `destinations` | `id`, `owner_id`, `alias`, `masked_account`, `currency`, `supported_routes text[]` |
| `authorizations` | `id`, `owner_id`, `session_id`, `mode` (`immediate`/`notify`/`auto`), `status`, `version int` (optimistic concurrency), `input_usdc numeric(20,6)`, `min_payout_mxn numeric(20,2)`, `destination_id`, `deadline_utc`, `display_tz`, `selected_quote_id` (immediate only), `next_check_at`, `last_check_at`, `last_reason`, `idempotency_key`, `terms_hash`, `confirmed_at`. **UNIQUE(owner_id, idempotency_key)** |
| `quote_snapshots` | `id`, `authorization_id NULL`, `session_id`, `provider_id`, `quote_id UNIQUE`, all money fields, `eta_seconds`, `expires_at`, `source` (`fixture`), `fetched_at`, `tick` |
| `decision_events` | `id bigserial`, `authorization_id`, `seq int` (**UNIQUE(authorization_id, seq)**), `at`, `kind` (`checked`, `waiting_below_target`, `provider_error`, `no_eligible_route`, `matched`, `notified`, `claimed`, `revalidation_failed`, `claim_released`, `signed`, `broadcast`, `confirmed`, `payout_posted`, `payout_failed`, `canceled`, `expired`), `reason text`, `best_quote_id`, `payload jsonb` |
| `executions` | `id`, `authorization_id` **UNIQUE** (one execution per authorization), `quote_id`, `route_id`, `recipient_address`, `amount_units numeric(78,0)`, `chain_id`, `token`, `nonce`, `signed_tx bytea` (**never serialized out**), `tx_hash`, `chain_status` (`prepared`/`broadcast`/`confirmed`/`reverted`/`unknown`), `payout_status` (`not_started`/`pending`/`posted`/`failed`), `payout_mxn`, `payout_attempts`, `settlement_mode` (`testnet`/`simulated`) |
| `notifications` | `id`, `owner_id`, `authorization_id`, `kind`, `body`, `read_at`, **UNIQUE(authorization_id, kind)** (one match notification) |

Migrations via Alembic. Seed script (`make seed`) creates the demo user, destination, and a fresh demo session.

## 5. State machines

### 5.1 Authorization

```
immediate:  confirmed ──claim──▶ executing ──▶ transfer_pending ──▶ transfer_confirmed ──▶ completed
                 │                    │                                  │
                 └─ requote_required ◀┘ (quote changed/expired)          └─▶ payout_pending (retry payout only)

notify:     watching ──match──▶ notified (terminal)
               ├──cancel──▶ canceled
               └──deadline──▶ expired

auto:       watching ──match──▶ claimed ──revalidate ok──▶ executing ──▶ … (as immediate)
               ▲                   │
               └── claim_released ◀┘ (revalidation failed, time remains)
               ├──cancel──▶ canceled          (only while status = watching)
               └──deadline──▶ expired         (never executes after deadline)
```

- Cancel: `UPDATE authorizations SET status='canceled' WHERE id=:id AND status='watching' RETURNING id`. Zero rows means **409 Conflict** with the current status.
- Any terminal state (`notified`, `canceled`, `expired`, `completed`) is never re-entered.

### 5.2 Execution

`prepared` (signed bytes + hash persisted, committed) → `broadcast` → `confirmed` | `reverted` | `unknown`
Payout: `not_started` → `pending` → `posted` | `failed` (retry with the same execution id, idempotency key `exec:{id}:payout`)

## 6. Agent decision loop (README centerpiece)

```
every tick (fixture) or every POLL_INTERVAL (live):
  claim due watches:  SELECT … FROM authorizations
                       WHERE status='watching' AND next_check_at <= now
                       FOR UPDATE SKIP LOCKED LIMIT N
  for each watch:
    if now >= deadline:            → expired, event, stop
    quotes = gather(provider.quote(...) with timeout PROVIDER_TIMEOUT_MS)   # concurrent, bounded
    split into: ok_quotes, provider_errors (timeout/exception, recorded separately)
    eligible = ok_quotes minus
        unsupported destination
        expired quote
        input > budget
        now + eta + SAFETY_MARGIN(2 min) > deadline
    rank eligible by (net_mxn DESC, eta ASC, route_id ASC)
    best = eligible[0] or none
    if none:              event(no_eligible_route | provider_error), keep watching
    elif best.net < min:  event(waiting_below_target, "Best is B at 9,993.25, 6.75 short of 10,000"), keep watching
    elif mode == notify:  insert notification (unique), status=notified, event(matched, notified)
    elif mode == auto:    status=claimed, event(claimed) → execute()
    next_check_at = now + interval; last_reason = short reason
```

**execute() (auto and immediate):**
1. Re-fetch the **selected route's** quote. Its id differs from the matched one by design.
2. Revalidate *every* constraint: status still `claimed`, version unchanged, `terms_hash` matches the confirmed terms, now < deadline, quote unexpired, net ≥ min, ETA + margin ≤ deadline, amount ≤ authorized budget, destination supported, recipient comes from server config, chain id and token match config, wallet balance ≥ amount.
3. Fail → `claim_released`, status back to `watching` (auto) or `requote_required` (immediate), event with the precise reason.
4. Pass → insert `executions` (UNIQUE on authorization_id blocks a double pay) → settlement adapter.

**LLM role is bounded:** it only produces an `IntentDraft` (and optionally a one-sentence natural-language summary of a decision event). It never authorizes, never chooses an address, never triggers execution. Only `POST /authorizations` with reviewed structured terms creates authority.

## 7. Settlement adapter

Interface `Signer` with `FakeSigner` (tests and simulated mode) and `Web3Signer` (Base Sepolia).

Startup validation, surfaced at `GET /health/settlement`:
- `RPC_URL` reachable and `eth_chainId == EXPECTED_CHAIN_ID` (84532)
- `USDC_CONTRACT` has code, `decimals()==6`, and `symbol()=="USDC"`
- `SIGNER_PRIVATE_KEY` present, derived address == `SIGNER_ADDRESS` (if set)
- Route settlement addresses are valid checksummed addresses
- Any failure → `settlement_mode = "simulated"`, with reason shown as a banner ("Testnet execution disabled: RPC_URL not set").

Execution protocol:
1. Acquire `pg_advisory_xact_lock(hash(signer_address))` to serialize signing per wallet.
2. Nonce = `max(pending nonce from chain, last persisted nonce + 1)`.
3. Build `transfer(recipient, amount_units)`, sign, and **persist `signed_tx` + `tx_hash` + `chain_status='prepared'`, then COMMIT** before broadcast.
4. Broadcast. On success → `broadcast`. On timeout or error → `unknown` (never re-sign).
5. Reconciler (worker startup and every loop): for `prepared`/`broadcast`/`unknown` executions, call `eth_getTransactionReceipt(tx_hash)`. If none and not in mempool, **rebroadcast the identical stored bytes**. With a receipt: require `status==1` **and** a `Transfer(from=signer, to=recipient, value=amount_units)` log from `USDC_CONTRACT`. Only then `confirmed`.
6. After `confirmed`: simulated payout posts `payout_mxn = quote.net_mxn` (provider deducts its fee internally). Failure → `transfer_confirmed / payout_pending`, retry payout only.

Logging: a structlog processor redacts `signed_tx`, `private_key`, and anything matching `0x[0-9a-f]{64}` on key fields. API schemas never include `signed_tx`.

### 7.1 Demo transfer amount: **known risk, needs your call before Phase 3**

Circle's testnet faucet dispenses small amounts (on the order of 10–20 USDC per request, rate-limited; **verify the current limit at faucet.circle.com**). Accumulating 600 test USDC may take days. Options:
- **(Recommended)** `DEMO_TRANSFER_SCALE=0.01`: the authorization and quotes stay at 600 USDC, and the real onchain transfer is 6.00 USDC. The receipt says explicitly: *"Testnet transfer scaled 1:100 for faucet limits: 6.00 test USDC sent."* This is honest, cheap, and supports many hosted-demo runs.
- `DEMO_TRANSFER_SCALE=1`: send the full 600 once you've farmed enough faucet USDC (record the video this way if you can).

The spending limit and balance checks apply to the **actual** onchain amount.

## 8. API

All endpoints are bound to the demo session cookie (`rs_session`, created on first request). Errors use `{error: {code, message, details}}`.

| Method | Path | Notes |
|---|---|---|
| POST | `/quotes` | `{amount_usdc, corridor:"USDC-MXN", destination_id, deadline?}` → `{quotes:[ranked], excluded:[{route_id, reason}], provider_errors:[…], clock:{now, tick}, settlement:{mode, chain_id}}` |
| POST | `/intents/parse` | `{text, display_tz?}` → `{draft: IntentDraft, missing:[field], ambiguities:[{field, question}], source:"claude"\|"rules"}`. Creates nothing. Without a key → 200 with `source:"unavailable"` so the UI shows the form. |
| POST | `/authorizations` | Header `Idempotency-Key`. Body: reviewed terms + `mode`. `immediate` requires `selected_quote_id`, and that quote must still be current (else **409 `quote_changed`** with the fresh quote → UI asks for fresh confirmation). Same key + same terms → the original response. Same key + different terms → **422**. |
| GET | `/authorizations/{id}` | Terms (with tz-rendered deadline), status, `last_check_at`, `next_check_at`, `last_reason`, ordered events, receipt `{execution, tx_hash, explorer_url, onchain_amount, settlement_mode, quoted_net_mxn, simulated_payout_mxn, payout_status}` |
| GET | `/authorizations` | List for the session (watch dashboard) |
| POST | `/authorizations/{id}/cancel` | 200 or 409 `already_claimed` / `already_terminal` |
| GET | `/notifications` | In-app notifications |
| POST | `/demo/advance` | Demo mode only (`DEMO_MODE=true`, else 404). Advances the session's fixture clock one tick and runs **one worker evaluation** synchronously. Returns new tick and affected authorizations. |
| POST | `/demo/reset` | New session with fresh clock |
| POST | `/demo/chaos` | Toggle `{provider_a_down, provider_b_timeout, drop_broadcast_response, fail_next_payout}` for the session |
| GET | `/health`, `/health/settlement` | Liveness, settlement-mode status |

`IntentDraft` schema (also the Claude tool input schema):
```json
{ "amount": "600", "currency": "USDC", "min_payout_mxn": "10000",
  "destination_alias": "My BBVA account", "deadline_local": "2026-11-27T17:00",
  "time_zone": "America/Mexico_City", "mode": "notify" }
```
Every field is nullable in the draft. The server computes `missing` and, from the model's `ambiguities`, generates questions (e.g. "Friday" when it's already Friday after 5 p.m. → ask "today or next week?"). The mode defaults to `notify` unless the user explicitly asks for automatic conversion. Even then the UI preselects Notify and shows Auto as an explicit opt-in.

## 9. Frontend (React + TS)

Screens:
1. **Compare**: amount input (default 600), destination, two route cards ranked by net MXN. Each card has a big net-MXN figure, a "rate looks better" badge on A to tell the story, and an expandable **fee waterfall** (`600 → −2 USDC fee → 598 × 16.85 = 10,076.30 → −100 MXN → 9,976.30`). Shows quote expiry countdown, ETA rendered in the user's tz, labels `Synthetic quote` and `Gas: demo-sponsored`, and a settlement-mode banner.
2. **Convert now modal**: exact input, minimum payout (= quoted net), destination, quote id and expiry. If the quote expires or changes, the confirm button turns into "Quote changed: review new quote".
3. **Watch builder**: a free-text box ("Ask the agent") → editable draft form, plus plain form tabs. The review panel shows the resolved date ("Friday, Nov 27, 2026, 5:00 p.m. CST (UTC−6)"), destination, total debit, minimum payout, and a Notify (default) / Auto-convert radio with an explicit consequence line for Auto.
4. **Watch detail**: status pill, last check, next check, short reason, a **decision timeline** (vertical, each event with a reason and best quote), and a Cancel button disabled once claimed.
5. **Receipt**: two columns. Left: original authorization and selected quote. Right: onchain transfer (amount, hash, explorer link, confirmation status) and simulated payout. The quoted vs. simulated payout appear side by side, with "Simulated" stamps.
6. **Demo control bar** (dev drawer, visible in demo mode): tick and clock, Advance, Reset, chaos toggles, settlement status.

The client polls `GET /authorizations/{id}` every 2 s while it's non-terminal. Server-sent events are not needed.

## 10. Configuration (`.env.example`)

```
DATABASE_URL=postgresql+psycopg://rampscout:rampscout@localhost:5432/rampscout
DEMO_MODE=true
DEMO_CLOCK_START=2026-11-27T17:00:00Z
DEMO_TICK_SECONDS=900
QUOTE_TTL_SECONDS=120
SAFETY_MARGIN_SECONDS=120
PROVIDER_TIMEOUT_MS=1500
POLL_INTERVAL_SECONDS=30
# Settlement (missing RPC_URL or SIGNER_PRIVATE_KEY → simulated mode)
RPC_URL=
EXPECTED_CHAIN_ID=84532
USDC_CONTRACT=0x036CbD53842c5426634e7929541eC2318f3dCF7e   # verify at developers.circle.com/stablecoins/usdc-contract-addresses
SIGNER_PRIVATE_KEY=
SIGNER_ADDRESS=
ROUTE_A_SETTLEMENT_ADDRESS=
ROUTE_B_SETTLEMENT_ADDRESS=
DEMO_TRANSFER_SCALE=0.01
MAX_ONCHAIN_TRANSFER_USDC=10
EXPLORER_TX_URL=https://sepolia.basescan.org/tx/
# Optional LLM
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-haiku-5-5
CORS_ORIGINS=http://localhost:5173
```
The chain ID, USDC address, and explorer above come from memory and **must be re-verified against Base and Circle docs during Phase 3**. The result goes in `docs/TESTNET_SETUP.md` with links.

## 11. Acceptance tests (pytest, against real Postgres)

| # | Test |
|---|---|
| Q1 | Fixture tick 0/1 payouts equal exactly `9976.30`, `9993.25`, `10023.20` (string compare) |
| Q2 | Higher rate (A) ranks below B at tick 0 |
| Q3 | Tie → earlier ETA wins; full tie → route id |
| Q4 | Route whose ETA + 2 min margin passes the deadline is excluded with reason `arrives_after_deadline`, even if highest paying |
| Q5 | Provider A down / timeout → B still returned and eligible; error listed in `provider_errors`, not `excluded` |
| Q6 | Expired quote excluded; over-budget excluded; unsupported destination excluded |
| Q7 | Money never serialized as float; rounding is ROUND_DOWN at end only |
| W1 | Watch 10,000 MXN: tick 0 → `waiting_below_target`; advance → tick 1 → match on B |
| W2 | Notify mode: match creates exactly one notification, status `notified`, **zero executions, signer never called** |
| W3 | Canceled watch never executes; cancel after claim → 409 |
| W4 | Deadline reached → `expired`, never executes even if a later quote qualifies |
| W5 | Stale quote: matched quote expires before signing → refresh + revalidate; if the refreshed quote is below target → claim released, still watching |
| W6 | Incomplete terms (missing min/deadline/destination) → 422; amount ≤ 0 → 422; deadline in past → 422 |
| W7 | Intent parse without API key returns `unavailable`; with mocked Claude returns draft + `missing` |
| W8 | Immediate mode with a changed/expired quote id → 409 `quote_changed` |
| S1 | Two workers evaluate the same due watch concurrently (threads, separate connections) → exactly one execution, one signer call |
| S2 | Same idempotency key posted twice concurrently → one authorization, identical responses; same key + different terms → 422 |
| S3 | Broadcast response dropped → status `unknown`; "restart" (new worker instance) → reconciler queries the **original hash**; FakeSigner asserts no second sign and only identical-bytes rebroadcast |
| S4 | Transfer confirmed + payout fails → `payout_pending`; retry posts payout with the same execution id; no new transfer |
| S5 | Receipt with wrong Transfer log (wrong recipient/amount) → not confirmed |
| S6 | Missing RPC/signer → settlement mode `simulated`, receipts labeled simulated |
| S7 | Logs and API responses never contain `signed_tx` or the key (caplog scan) |

Frontend: Vitest for the money formatting and the fee waterfall component; one Playwright smoke test of the demo path (stretch).

## 12. Non-functional

- Every money path is covered by tests. CI runs `ruff`, `mypy --strict` on `rampscout/domain`, `pytest`, `tsc --noEmit`, `eslint`, and `vitest`.
- The hosted demo is per-visitor session isolated. Onchain sends are capped by `MAX_ONCHAIN_TRANSFER_USDC` and a global daily cap (`DAILY_ONCHAIN_RUNS=20`); past the cap the session falls back to simulated, with a banner.
- No secrets in the repo; `.env` is gitignored; Render secrets are set in the dashboard.
