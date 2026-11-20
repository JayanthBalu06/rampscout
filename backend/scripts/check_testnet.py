"""Run the same live checks the app runs before enabling testnet settlement.

python -m scripts.check_testnet
"""

from __future__ import annotations

from rampscout.config import get_settings
from rampscout.settlement.status import verify_testnet


def main() -> None:
    s = verify_testnet(get_settings())
    print(f"mode:    {s.mode}")
    print(f"reason:  {s.reason}")
    if s.signer_address:
        print(f"signer:  {s.signer_address}")
        print(f"balance: {s.signer_usdc} USDC, {s.signer_eth} ETH")
    for name, ok in s.checks.items():
        print(f"  [{'x' if ok else ' '}] {name}")
    raise SystemExit(0 if s.mode == "testnet" else 1)


if __name__ == "__main__":
    main()
