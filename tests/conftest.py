import os

os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN-FOR-PYTEST"
os.environ["WEBAPP_URL"] = ""
os.environ["PUBLIC_URL"] = ""
os.environ["WEBHOOK_SECRET"] = ""
os.environ.pop("RENDER_EXTERNAL_URL", None)

import pytest

import scanner

BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@pytest.fixture(autouse=True)
def clear_rugcheck_cache():
    scanner._rugcheck_cache.clear()
    yield
    scanner._rugcheck_cache.clear()


@pytest.fixture
def dexscreener_pairs():
    return [
        {
            "baseToken": {"symbol": "DUST", "name": "Dust pool"},
            "priceUsd": "0.1",
            "liquidity": {"usd": 50},
            "volume": {"h24": 10},
        },
        {
            "baseToken": {"symbol": "Bonk", "name": "Bonk"},
            "priceUsd": "0.000002357",
            "liquidity": {"usd": 230519.95},
            "volume": {"h24": 405716.67},
        },
    ]


@pytest.fixture
def mint_account():
    return {
        "result": {
            "value": {
                "data": {
                    "parsed": {
                        "type": "mint",
                        "info": {"mintAuthority": None, "freezeAuthority": None},
                    }
                }
            }
        }
    }


@pytest.fixture
def rugcheck_summary():
    return {
        "score_normalised": 7,
        "lpLockedPct": 19.428788418908034,
        "risks": [{"name": "Mutable metadata", "level": "warn"}],
    }
