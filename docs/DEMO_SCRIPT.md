# Two-minute demo script

**Setup (before you present):** `make stack` (or `make up`, `make api`, `make worker`, `make web`), then open the app and click **Reset**. If you'll show a real transfer, finish [TESTNET_SETUP.md](TESTNET_SETUP.md) first and confirm the green "Testnet settlement" banner. Record one full testnet run ahead of time in case the venue Wi-Fi fails. `make demo` runs the same journey in a terminal as a second fallback.

| Time | Do | Say |
|---|---|---|
| 0:00 | **Compare** tab, 600 USDC. | "A freelancer in Mexico was paid 600 USDC. Every off-ramp advertises a rate. RampScout ranks routes by the pesos that actually land in the bank." |
| 0:15 | Open **Fee breakdown** on both cards. Point at "Higher rate, fewer pesos". | "Route A has the better rate, 16.85, but a 2 USDC fee and a 100 peso withdrawal fee. Route B nets MX$9,993.25, about 17 pesos more. All the math is decimal and rounds down once, at the end." |
| 0:35 | **Watch for a target** → *Use the example* → **Draft terms**. | "Say I'd rather wait for 10,000 pesos by Friday 5 p.m. Claude turns my sentence into a typed draft. It only drafts: it can't authorize anything or pick a wallet." |
| 0:50 | **Review terms**. Point at the exact deadline, total debit and minimum. Choose **Auto-convert**. **Confirm**. | "I approve exact terms: 600 USDC in, at least MX$10,000 out, Friday 5:00 PM Mexico City time, my BBVA account. Notify is the default. I'm opting into auto." |
| 1:05 | Watch page: first decision. | "First check: best is B at MX$9,993.25, MX$6.75 short. So it waits, and it shows when it'll check next. This lives in Postgres and the worker, so closing the browser changes nothing." |
| 1:15 | **Advance 1 tick**. | "Fifteen demo minutes later B moves to 16.80, MX$10,023.20. The agent claims the watch, fetches a fresh quote and re-checks every limit right before signing. If anything had changed, it would release the claim and keep watching." |
| 1:30 | **Receipt**: click the tx hash. | "Here's a real USDC transfer on Base Sepolia, scaled down for faucet limits, verified by its receipt and Transfer log. Peso conversion and the bank deposit are simulated, and labeled that way." |
| 1:45 | Point at the quoted vs simulated payout panel. Optional: tick **Lose next broadcast response**, convert again, click **Restart worker**. | "Quoted MX$10,023.20, paid MX$10,023.20. And if the network response is lost mid-payment, it never signs twice: it saved the transaction before sending and reconciles by the original hash." |

## Alternative opening: Send (live market data)

| Time | Do | Say |
|---|---|---|
| 0:00 | **Send** tab, Mamá selected, 600 USDC. | "I want to send 600 USDC to my mom in Mexico. I pick her and an amount; that's all I enter." |
| 0:10 | Point at *routes compared* and the price-protection minimum. Open **How this route works**. | "RampScout just priced every route through Bitso's live order books. USD then pesos beats USDT then pesos by about 9 pesos today, and the BTC detour by about 60. Each hop walks the real book with Bitso's real fees. Bitso has no USDC market, so that first swap is labeled as an assumption." |
| 0:30 | **Show other routes**, then click **Ana** (wallet). | "For a crypto contact there's nothing to convert: it's a direct onchain transfer." |
| 0:40 | Back to Mamá → **Send** → **Confirm**. Receipt. | "Right before signing it re-prices the same route on fresh data. If Mamá would get less than the minimum, nothing moves. Here's the Base Sepolia transfer, and the payout matching the quote." |

**Reset between runs** with the Reset button. Each browser has its own demo clock.

## Backup lines for questions

- *"What stops double payments?"* One execution row per authorization (a database UNIQUE constraint), row-locked claims, idempotency keys on confirmation, and a per-wallet advisory lock for signing. Tests race 4 workers and 5 duplicate confirmations against each other. Exactly one transfer is signed.
- *"What if the AI is wrong?"* The server re-validates every drafted field. Ambiguities like "CST" or "Friday" after 5 p.m. come back as questions. Only terms the user reviews and confirms create authority.
- *"Is waiting always better?"* No. The UI says so before you confirm, and a watch can expire unfilled. The backtest under Future work in the README is how we'd measure that.
