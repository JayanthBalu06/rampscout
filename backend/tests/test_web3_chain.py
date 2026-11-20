"""Base Sepolia client pieces that can be verified offline: transaction building and
signing, and Transfer-log parsing. (Live RPC checks run via /health/settlement.)"""

from eth_account import Account
from pydantic import SecretStr
from web3 import Web3

from rampscout.config import Settings
from rampscout.settlement.status import verify_testnet
from rampscout.settlement.web3_chain import TRANSFER_TOPIC, Web3Chain, parse_transfer_logs

USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def offline_settings(**kw):
    acct = Account.create()
    base = dict(
        rpc_url="http://127.0.0.1:9",
        signer_private_key=SecretStr(acct.key.hex()),
        route_a_settlement_address=Account.create().address,
        route_b_settlement_address=Account.create().address,
        usdc_contract=USDC,
        expected_chain_id=84532,
    )
    base.update(kw)
    return Settings(**base), acct


def test_builds_and_signs_an_eip1559_usdc_transfer_offline():
    settings, acct = offline_settings()
    chain = Web3Chain(settings)
    to = settings.route_b_settlement_address
    tx = chain.build_transfer(nonce=7, to=to, amount_units=6_000_000, gas=80_000, max_fee=2, tip=1)
    assert tx["chainId"] == 84532 and tx["to"] == USDC and tx["value"] == 0
    assert tx["data"].startswith("0xa9059cbb")  # transfer(address,uint256)
    signed = acct.sign_transaction(tx)
    assert Account.recover_transaction(signed.raw_transaction) == acct.address
    assert Web3.to_hex(Web3.keccak(signed.raw_transaction)) == Web3.to_hex(signed.hash)


def test_parses_only_erc20_transfer_logs():
    sender, recipient = Account.create().address, Account.create().address
    receipt = {
        "logs": [
            {"address": USDC, "topics": ["0x" + "00" * 32], "data": "0x"},  # other event
            {
                "address": USDC.lower(),
                "topics": [
                    TRANSFER_TOPIC,
                    "0x" + "00" * 12 + sender[2:].lower(),
                    "0x" + "00" * 12 + recipient[2:].lower(),
                ],
                "data": "0x" + (6_000_000).to_bytes(32, "big").hex(),
            },
        ]
    }
    (t,) = parse_transfer_logs(receipt)
    assert (t.token, t.sender, t.recipient, t.value) == (USDC, sender, recipient, 6_000_000)


def test_unreachable_rpc_disables_testnet_with_reason():
    settings, _ = offline_settings()
    status = verify_testnet(settings)
    assert status.mode == "simulated"
    assert "RPC unreachable" in status.reason


def test_bad_route_address_disables_testnet():
    settings, acct = offline_settings(route_a_settlement_address="0xnot-an-address")
    status = verify_testnet(settings)
    assert status.mode == "simulated"
    assert "ROUTE_A_SETTLEMENT_ADDRESS" in status.reason
