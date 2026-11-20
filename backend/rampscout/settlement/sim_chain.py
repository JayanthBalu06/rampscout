"""A database-backed stand-in for a chain node, shared by API and worker processes.

It is deliberately *not* a shortcut: signing, broadcasting, receipts and nonces behave
like a node so the same settlement state machine (persist-before-broadcast, reconcile by
hash, resend identical bytes) runs locally. Everything it produces is labeled simulated.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

from sqlalchemy import func, select
from web3 import Web3

from rampscout.db.models import SimChainTx
from rampscout.db.session import SessionLocal
from rampscout.settlement.chain import BroadcastUnknown, Receipt, SignedTx, TransferLog

SIM_SIGNER = "0x5100000000000000000000000000000000005160"
SIM_TOKEN = "0x5100000000000000000000000000000000005dc0"
SIM_ROUTE_RECIPIENTS = {
    "A": "0x5100000000000000000000000000000000000a0a",
    "B": "0x5100000000000000000000000000000000000b0b",
}
_SIM_KEY = b"rampscout-local-sim-signer"  # not a secret: this ledger moves nothing
_GENESIS_BLOCK = 1_000_000


class SimulatedChain:
    label = "local simulated ledger"
    signer_address = SIM_SIGNER

    def __init__(self, *, drop_requests: int = 0) -> None:
        # Test hook: lose the next N broadcasts *before* they reach the "node".
        self.drop_requests = drop_requests

    def chain_id(self) -> int:
        return 0

    def token_info(self) -> tuple[str, int]:
        return ("USDC", 6)

    def token_balance(self, address: str) -> int:
        return 1_000_000 * 10**6

    def native_balance(self, address: str) -> int:
        return 10**18

    def pending_nonce(self, address: str) -> int:
        with SessionLocal() as db:
            n = db.scalar(
                select(func.count())
                .select_from(SimChainTx)
                .where(SimChainTx.signer == address.lower(), SimChainTx.received.is_(True))
            )
            return int(n or 0)

    def sign_transfer(self, *, nonce: int, to: str, amount_units: int) -> SignedTx:
        payload = json.dumps(
            {
                "from": SIM_SIGNER,
                "to": to.lower(),
                "token": SIM_TOKEN,
                "amount": amount_units,
                "nonce": nonce,
            },
            sort_keys=True,
        ).encode()
        raw = payload + b"|sig:" + hmac.new(_SIM_KEY, payload, hashlib.sha256).digest()
        tx_hash = Web3.to_hex(Web3.keccak(raw))
        with SessionLocal() as db:
            if db.get(SimChainTx, tx_hash) is None:
                db.add(
                    SimChainTx(
                        tx_hash=tx_hash,
                        raw=raw,
                        signer=SIM_SIGNER,
                        token=SIM_TOKEN,
                        recipient=to.lower(),
                        amount_units=Decimal(amount_units),
                        nonce=nonce,
                        received=False,
                        send_count=0,
                    )
                )
                db.commit()
        return SignedTx(raw=raw, tx_hash=tx_hash)

    def send_raw(self, raw: bytes) -> str:
        tx_hash = Web3.to_hex(Web3.keccak(raw))
        if self.drop_requests > 0:
            self.drop_requests -= 1
            raise BroadcastUnknown("connection reset before the node answered")
        with SessionLocal() as db:
            tx = db.get(SimChainTx, tx_hash, with_for_update=True)
            if tx is None or tx.raw != raw:
                raise BroadcastUnknown("unknown transaction bytes")
            tx.received = True
            tx.send_count += 1
            db.commit()
        return tx_hash

    def get_receipt(self, tx_hash: str) -> Receipt | None:
        with SessionLocal() as db:
            tx = db.get(SimChainTx, tx_hash, with_for_update=True)
            if tx is None or not tx.received:
                return None
            if tx.block_number is None:  # "mine" on first look
                top = db.scalar(select(func.max(SimChainTx.block_number)))
                tx.block_number = (top or _GENESIS_BLOCK) + 1
                db.commit()
            return Receipt(
                status=1,
                block_number=tx.block_number,
                transfers=(
                    TransferLog(
                        token=tx.token,
                        sender=tx.signer,
                        recipient=tx.recipient,
                        value=int(tx.amount_units),
                    ),
                ),
            )

    def is_known(self, tx_hash: str) -> bool:
        with SessionLocal() as db:
            tx = db.get(SimChainTx, tx_hash)
            return bool(tx and tx.received)
