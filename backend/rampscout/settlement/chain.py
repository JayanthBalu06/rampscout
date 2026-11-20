"""Chain abstraction shared by the Base Sepolia client and the local simulated ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BroadcastUnknown(Exception):
    """We don't know whether the node accepted the tx (timeout, dropped connection).
    The only safe follow-up is to query the hash or resend the *same* bytes."""


class BroadcastRejected(Exception):
    """The node definitively refused the tx (e.g. insufficient funds). It will not land."""


@dataclass(frozen=True)
class SignedTx:
    raw: bytes
    tx_hash: str


@dataclass(frozen=True)
class TransferLog:
    token: str
    sender: str
    recipient: str
    value: int


@dataclass(frozen=True)
class Receipt:
    status: int  # 1 success, 0 reverted
    block_number: int
    transfers: tuple[TransferLog, ...]


class ChainClient(Protocol):
    label: str  # "Base Sepolia" or "local simulated ledger"
    signer_address: str

    def chain_id(self) -> int: ...
    def token_info(self) -> tuple[str, int]: ...
    def token_balance(self, address: str) -> int: ...
    def native_balance(self, address: str) -> int: ...
    def pending_nonce(self, address: str) -> int: ...
    def sign_transfer(self, *, nonce: int, to: str, amount_units: int) -> SignedTx: ...
    def send_raw(self, raw: bytes) -> str: ...
    def get_receipt(self, tx_hash: str) -> Receipt | None: ...
    def is_known(self, tx_hash: str) -> bool: ...


def same_address(a: str, b: str) -> bool:
    return a.lower() == b.lower()
