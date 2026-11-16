import asyncio
import os

import aiohttp

from rimex.domain.models import TokenReport

DEFAULT_URL = "https://api.mainnet-beta.solana.com"
FALLBACK_URLS = ["https://solana-rpc.publicnode.com"]


def rpc_urls() -> list[str]:
    primary = os.getenv("SOLANA_RPC_URL") or DEFAULT_URL
    return list(dict.fromkeys([primary, *FALLBACK_URLS]))


async def fetch_mint_account(session: aiohttp.ClientSession, address: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [address, {"encoding": "jsonParsed"}],
    }
    last_error: Exception | None = None
    for url in rpc_urls():
        try:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            last_error = error
            continue
        if "error" in data:
            last_error = aiohttp.ClientError(f"RPC error: {data['error']}")
            continue
        return data
    raise last_error


def apply_mint_account(report: TokenReport, data: dict) -> None:
    account = (data.get("result") or {}).get("value") or {}
    account_data = account.get("data")
    parsed = account_data.get("parsed") if isinstance(account_data, dict) else None
    if not parsed or parsed.get("type") != "mint":
        report.errors.append("Solana RPC: address is not a token mint")
        return
    info = parsed["info"]
    report.authorities_loaded = True
    report.mint_authority = info.get("mintAuthority")
    report.freeze_authority = info.get("freezeAuthority")
    report.token_program = account_data.get("program")
    apply_extensions(report, info.get("extensions") or [])


def apply_extensions(report: TokenReport, extensions: list[dict]) -> None:
    states = {item.get("extension"): item.get("state") or {} for item in extensions}

    fee_config = states.get("transferFeeConfig")
    if fee_config is not None:
        fees = [
            (fee_config.get(key) or {}).get("transferFeeBasisPoints") or 0
            for key in ("olderTransferFee", "newerTransferFee")
        ]
        report.transfer_fee_bps = max(fees)
        report.transfer_fee_mutable = bool(fee_config.get("transferFeeConfigAuthority"))

    report.transfer_hook_program = (states.get("transferHook") or {}).get("programId")
    report.permanent_delegate = (states.get("permanentDelegate") or {}).get("delegate")
