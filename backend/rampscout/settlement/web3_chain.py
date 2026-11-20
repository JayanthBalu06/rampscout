"""Base Sepolia client: real ERC-20 USDC transfers signed by a dedicated test wallet.

The private key lives only in this object (from SIGNER_PRIVATE_KEY). It is never logged,
returned by the API, or stored in the database; only the signed bytes are persisted,
which are needed to resend the identical transaction after a crash.
"""

from __future__ import annotations

from typing import Any

import requests
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from rampscout.config import Settings
from rampscout.settlement.chain import (
    BroadcastRejected,
    BroadcastUnknown,
    Receipt,
    SignedTx,
    TransferLog,
)

ERC20_ABI: list[dict[str, Any]] = [
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
]
TRANSFER_TOPIC = Web3.to_hex(Web3.keccak(text="Transfer(address,address,uint256)"))


def _hex(b: Any) -> str:
    return b if isinstance(b, str) else Web3.to_hex(b)


def parse_transfer_logs(receipt: dict[str, Any]) -> tuple[TransferLog, ...]:
    out = []
    for log in receipt.get("logs", []):
        topics = [_hex(t) for t in log.get("topics", [])]
        if len(topics) != 3 or topics[0].lower() != TRANSFER_TOPIC.lower():
            continue
        data = log.get("data", b"")
        value = int(_hex(data), 16) if data not in (b"", "0x") else 0
        out.append(
            TransferLog(
                token=Web3.to_checksum_address(log["address"]),
                sender=Web3.to_checksum_address("0x" + topics[1][-40:]),
                recipient=Web3.to_checksum_address("0x" + topics[2][-40:]),
                value=value,
            )
        )
    return tuple(out)


class Web3Chain:
    label = "Base Sepolia"

    def __init__(self, settings: Settings, w3: Web3 | None = None) -> None:
        self._settings = settings
        self._account = Account.from_key(settings.signer_private_key.get_secret_value())
        self.signer_address: str = self._account.address
        self.w3 = w3 or Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
        send_url = settings.rpc_send_url or settings.rpc_url
        self._send_w3 = (
            self.w3
            if send_url == settings.rpc_url
            else Web3(Web3.HTTPProvider(send_url, request_kwargs={"timeout": 10}))
        )
        self.token = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.usdc_contract), abi=ERC20_ABI
        )

    def chain_id(self) -> int:
        return int(self.w3.eth.chain_id)

    def token_info(self) -> tuple[str, int]:
        return (self.token.functions.symbol().call(), int(self.token.functions.decimals().call()))

    def token_balance(self, address: str) -> int:
        return int(self.token.functions.balanceOf(Web3.to_checksum_address(address)).call())

    def native_balance(self, address: str) -> int:
        return int(self.w3.eth.get_balance(Web3.to_checksum_address(address)))

    def pending_nonce(self, address: str) -> int:
        return int(self.w3.eth.get_transaction_count(Web3.to_checksum_address(address), "pending"))

    def _fees(self) -> tuple[int, int]:
        base = int(self.w3.eth.get_block("latest")["baseFeePerGas"])
        tip = int(self.w3.eth.max_priority_fee)
        return base * 2 + tip, tip

    def _gas(self, to: str, amount_units: int) -> int:
        est = self.token.functions.transfer(to, amount_units).estimate_gas(
            {"from": self.signer_address}
        )
        return int(est * 1.25)

    def build_transfer(
        self, *, nonce: int, to: str, amount_units: int, gas: int, max_fee: int, tip: int
    ) -> dict[str, Any]:
        to = Web3.to_checksum_address(to)
        return {
            "type": 2,
            "chainId": self._settings.expected_chain_id,
            "nonce": nonce,
            "to": self.token.address,
            "value": 0,
            "data": self.token.encode_abi("transfer", args=[to, amount_units]),
            "gas": gas,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": tip,
        }

    def sign_transfer(self, *, nonce: int, to: str, amount_units: int) -> SignedTx:
        max_fee, tip = self._fees()
        tx = self.build_transfer(
            nonce=nonce,
            to=to,
            amount_units=amount_units,
            gas=self._gas(Web3.to_checksum_address(to), amount_units),
            max_fee=max_fee,
            tip=tip,
        )
        signed = self._account.sign_transaction(tx)
        return SignedTx(raw=bytes(signed.raw_transaction), tx_hash=Web3.to_hex(signed.hash))

    def send_raw(self, raw: bytes) -> str:
        expected = Web3.to_hex(Web3.keccak(raw))
        try:
            return Web3.to_hex(self._send_w3.eth.send_raw_transaction(raw))
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise BroadcastUnknown(type(exc).__name__) from None
        except Exception as exc:  # web3 RPC errors carry the node's message
            msg = str(exc).lower()
            if "already known" in msg or "known transaction" in msg:
                return expected
            if "nonce too low" in msg or "replacement transaction underpriced" in msg:
                # A tx with this nonce already exists: maybe ours. Reconcile by hash.
                raise BroadcastUnknown("nonce already used; reconciling by hash") from None
            raise BroadcastRejected(msg[:200]) from None

    def get_receipt(self, tx_hash: str) -> Receipt | None:
        try:
            r = self.w3.eth.get_transaction_receipt(tx_hash)  # type: ignore[arg-type]
        except TransactionNotFound:
            return None
        return Receipt(
            status=int(r["status"]),
            block_number=int(r["blockNumber"]),
            transfers=parse_transfer_logs(dict(r)),
        )

    def is_known(self, tx_hash: str) -> bool:
        try:
            self.w3.eth.get_transaction(tx_hash)  # type: ignore[arg-type]
            return True
        except TransactionNotFound:
            return False
