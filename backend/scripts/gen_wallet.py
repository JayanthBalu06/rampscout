"""Create dedicated Base Sepolia test wallets for RampScout.

    python -m scripts.gen_wallet            # print what would be written
    python -m scripts.gen_wallet --write    # write signer + route addresses into ../.env

* The signer key goes into .env (gitignored). Fund ONLY this wallet, and only with test funds.
* Route A/B settlement wallets receive the demo transfers. Their keys are saved to
  ../secrets/route_wallets.json (gitignored) so you can sweep test USDC back later.
Never reuse these keys anywhere else; never use a wallet that holds real funds.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from eth_account import Account

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"
SECRETS = ROOT / "secrets" / "route_wallets.json"


def _set(env: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", env, flags=re.M):
        return re.sub(rf"^{key}=.*$", line, env, flags=re.M)
    return env.rstrip("\n") + f"\n{line}\n"


def main() -> None:
    write = "--write" in sys.argv
    signer, route_a, route_b = Account.create(), Account.create(), Account.create()
    print(f"Signer (fund this one):  {signer.address}")
    print(f"Route A settlement:      {route_a.address}")
    print(f"Route B settlement:      {route_b.address}")
    if not write:
        print("\nDry run. Re-run with --write to save into .env and secrets/.")
        return
    env = ENV.read_text() if ENV.exists() else (ROOT / ".env.example").read_text()
    if re.search(r"^SIGNER_PRIVATE_KEY=.+$", env, flags=re.M):
        sys.exit("SIGNER_PRIVATE_KEY is already set in .env; refusing to overwrite a wallet.")
    for k, v in (
        ("SIGNER_PRIVATE_KEY", "0x" + signer.key.hex().removeprefix("0x")),
        ("SIGNER_ADDRESS", signer.address),
        ("ROUTE_A_SETTLEMENT_ADDRESS", route_a.address),
        ("ROUTE_B_SETTLEMENT_ADDRESS", route_b.address),
    ):
        env = _set(env, k, v)
    ENV.write_text(env)
    SECRETS.parent.mkdir(exist_ok=True)
    SECRETS.write_text(
        json.dumps(
            {
                "route_a": {"address": route_a.address, "private_key": route_a.key.hex()},
                "route_b": {"address": route_b.address, "private_key": route_b.key.hex()},
            },
            indent=2,
        )
    )
    SECRETS.chmod(0o600)
    print(f"\nWrote .env and {SECRETS.relative_to(ROOT)} (both gitignored).")
    print("Next: fund the signer with Base Sepolia ETH + test USDC, then run")
    print("  make check-testnet")


if __name__ == "__main__":
    main()
