## Inspiration

Freelancers across Latin America are increasingly paid in USDC. To pay rent they have to get those dollars into pesos, and every off-ramp advertises an exchange rate. The rate is the wrong number to look at. A provider quoting **16.85 MXN/USDC** with a 2 USDC fee and a 100-peso withdrawal fee pays *less* than one quoting **16.75** with smaller fees. We wanted a wallet that ranks options by the only number that matters, **what actually lands in the recipient's account**, and an agent that can wait for a better price on your behalf without ever being able to spend more than you approved.

## What it does

RampScout is a USDC wallet that finds the best route for every payment.

- **Send anywhere.** Paste a wallet address and pick what they should receive (USDC, USDT, BTC or ETH), or pay a bank account in MXN, ARS, COP or BRL. Enter an amount. That's all. RampScout prices every route through **Bitso's live order books** and picks the one that delivers the most, e.g. `USDC → USD → MXN` beating `USDC → USDT → MXN` by about MX$9 and a BTC detour by about MX$60 on the same 600 USDC.
- **Ask the agent.** *"Send 600 USDC to Mamá when she gets at least 11,400 pesos by 5pm."* Claude turns that into a typed draft; you see what she'd get right now; you choose **Notify** or **Auto-send** and confirm. The agent re-checks live routes every 30 seconds, re-prices the exact route right before signing, never sends below your minimum, and gives up at the deadline without sending.
- **Real settlement.** The USDC leaves your wallet as a **real ERC-20 transfer on Base Sepolia**, verified by its receipt and Transfer log, with a Basescan link on every receipt.

## How we built it

**Stack:** FastAPI + PostgreSQL + a Python worker, React/TypeScript/Tailwind, web3.py on Base Sepolia, Bitso's public API, and Claude with structured JSON output for drafting.

**Routing.** Every conversion is a *leg*: a taker trade that walks one side of a Bitso order book level by level, an assumed stablecoin swap, an onchain transfer, or a payout. A hop with input \\( x \\), average fill price \\( \bar p(x) \\) (which depends on depth) and taker fee \\( f \\) yields

$$
\text{out} = \Big\lfloor\, x \cdot \bar p(x)\,(1 - f) \Big\rfloor_{\text{minor unit}}
$$

and a route is the composition of its hops. We rank all simple paths up to three conversions by received amount, then speed. We deliberately **don't** use the classic shortest-path trick of running Dijkstra over \\( -\log r \\): it only works when every fee is a pure percentage. Fixed fees (2 USDC, 100 MXN), order-book depth and per-hop rounding make cost depend on the amount, so the "best" route can flip with size. With eight currencies, exhaustive search is exact and takes milliseconds.

**Exactly-once payments.** Moving money is where software breaks, so most of the engineering went here:

- one execution row per authorization (`UNIQUE`), row-locked claims (`FOR UPDATE SKIP LOCKED`), idempotency keys bound to a hash of the confirmed terms;
- a per-wallet advisory lock serializes signing so nonces never collide;
- the signed transaction and its hash are **committed before broadcast**; if the network response is lost, the reconciler looks up the *original hash* or resends the *identical bytes*, never a new payment;
- a transfer counts only with receipt status 1 **and** the exact `Transfer(signer → recipient, amount)` log;
- if the payout step fails after the transfer confirms, only the payout is retried.

The demo includes chaos switches (provider down, lost broadcast response, failed payout) and a "Restart worker" button so you can watch recovery happen live.

**The agent can't overreach.** The model only drafts. The server re-validates every field, flags ambiguity ("CST": Chicago or Mexico City?) instead of guessing, and recipients are confirmed contacts that the model can never create. Nothing moves until the user confirms structured terms.

## Challenges we ran into

- **Bitso has no USDC market.** USDC enters through an explicitly labeled assumption leg (1:1, 0.05% fee); every later hop uses real books and real fees. The UI badges each hop as *Live*, *Assumption*, *Real · Base Sepolia* or *Simulated*.
- **Testnet faucets.** Circle's faucet gives 20 USDC every 2 hours, so real transfers are scaled 1:1000 (600 authorized → 0.60 USDC onchain), stated on every receipt.
- **Losing the broadcast response.** Distinguishing "sent but no reply" from "never sent" without ever signing twice required the persist-before-broadcast design and a reconciler that runs on startup and every loop.
- **Bugs our own tests caught:** two simultaneous first requests minting two demo sessions; crash recovery that could void a just-created send; tests that silently priced against the *live* market (now any test touching the network fails loudly).

## Accomplishments that we're proud of

- Real Base Sepolia transfers from the deployed app, verified onchain, e.g. a live Bitso-routed send: [0xd510…3fa7](https://sepolia.basescan.org/tx/0xd510fe1c1118965c1a324b4c6b6208ad630e4d8e412f9a801950731433c23fa7).
- 134 backend tests (including 4 racing workers and 5 duplicate confirmations producing exactly one transfer), 13 Playwright browser journeys, and CI on every push.
- Honest labeling everywhere: what's live, what's assumed, and what's simulated.

## What we learned

The interesting problems in payments aren't the happy path. They're the moment between "signed" and "confirmed", and the gap between a rate and a payout. We also learned to keep the LLM on a short leash: it's great at turning intent into structure, and the system is safer when that's *all* it does.

## What's next

Authenticated execution on the exchange legs (today they're priced live but settled as a simulation), a live USDC entry price from a DEX, more venues so routes can cross exchanges, and a backtest measuring how often waiting beats sending immediately.

| Real | Simulated |
|---|---|
| USDC transfer on Base Sepolia, Bitso prices and fees, routing, agent decisions | Fiat payouts (SPEI etc.), crypto withdrawals to non-USDC wallets, the USDC→USD/USDT entry swap (assumed) |
