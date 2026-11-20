# Testnet setup (Base Sepolia)

RampScout sends a **real ERC-20 USDC transfer on Base Sepolia** when a funded test wallet is configured. Without one, it settles on a clearly labeled local simulated ledger that runs the same state machine. This guide takes about 15 minutes, mostly waiting on faucets.

> Use **test funds only** and a wallet created for this project. Never put a key that holds real assets in `.env`.

## Network facts (verified 2026-11-20)

| Fact | Value | Source |
|---|---|---|
| Chain ID | `84532` | [docs.base.org: connecting to Base](https://docs.base.org/base-chain/quickstart/connecting-to-base) |
| Public RPC | `https://sepolia.base.org` (free, rate limited, "not suitable for production apps") | same |
| Send endpoint | `https://sepolia-sequencer.base.org` (for sending transactions only) | same |
| Explorer | `https://sepolia.basescan.org` | same |
| USDC contract | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | [Circle: USDC contract addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses) |
| Test USDC faucet | [faucet.circle.com](https://faucet.circle.com), select Base Sepolia: **20 USDC per address every 2 hours** | Circle faucet FAQ |
| Test ETH faucets | [Coinbase CDP faucet](https://portal.cdp.coinbase.com/onchain-tools/faucet) (up to 0.1 ETH / 24 h), [Alchemy](https://www.alchemy.com/faucets/base-sepolia), [QuickNode](https://faucet.quicknode.com/base/sepolia), [thirdweb](https://thirdweb.com/base-sepolia-testnet) | [docs.base.org: get funds](https://docs.base.org/get-started/get-funds) |

The chain ID and token were also checked live: `eth_chainId` returned `84532`, and the contract reports `symbol() = "USDC"` and `decimals() = 6`. The app repeats these checks before it enables testnet mode.

## Why transfers are scaled 1:100

The demo authorizes **600 USDC**, but the faucet gives 20 USDC every 2 hours. With `DEMO_TRANSFER_SCALE=0.01`, each conversion moves **6.00 test USDC** onchain. Quotes, authorization and payout math stay at 600. The quote view and receipt both state the scale. Set it to `1` once you have collected 600 test USDC if you want a full-size run for the video.

## Steps

1. **Create wallets** (from the repo root):

   ```bash
   make wallet
   ```

   This writes `SIGNER_PRIVATE_KEY`, `SIGNER_ADDRESS`, `ROUTE_A_SETTLEMENT_ADDRESS` and `ROUTE_B_SETTLEMENT_ADDRESS` into `.env` (gitignored). The route wallets' keys go into `secrets/route_wallets.json` (also gitignored) so you can sweep test USDC back later. It refuses to overwrite an existing signer.

2. **Fund the signer** printed by the script:
   - about 0.01 Base Sepolia ETH for gas, from any ETH faucet above (gas is demo-sponsored: the signer pays it, users don't)
   - 20 test USDC from faucet.circle.com, which covers 3 conversions at 6 USDC

3. **Set an RPC URL** in `.env`:

   ```bash
   RPC_URL=https://sepolia.base.org          # or an Alchemy / QuickNode Base Sepolia URL (more reliable)
   RPC_SEND_URL=https://sepolia-sequencer.base.org   # optional
   ```

4. **Verify** with the same checks the app runs:

   ```bash
   make check-testnet
   ```

   Expected output: `mode: testnet` with every check ticked. Anything else prints the exact reason, and the app stays in simulated mode with that reason shown in a banner.

5. **Restart** `make api` and `make worker` (or `make stack`). The banner now reads "Testnet settlement" and receipts link to `sepolia.basescan.org`.

## Safety limits (all in `.env`)

| Variable | Default | Effect |
|---|---|---|
| `MAX_AUTHORIZATION_USDC` | 1000 | No authorization above this amount |
| `MAX_ONCHAIN_TRANSFER_USDC` | 10 | Hard cap on any single onchain transfer |
| `DAILY_ONCHAIN_RUNS` | 20 | After this many testnet transfers in 24 h, the app falls back to simulated mode (protects a public demo's faucet funds) |
| `RECEIPT_WAIT_SECONDS` | 30 | How long a request waits for a receipt before the worker takes over |

The key only ever lives in process memory as an `eth_account` object. It is never logged, never stored in Postgres, and never returned by the API. Only the signed transaction bytes are stored, so that after a crash the *identical* transaction can be resent instead of signing a new payment.
