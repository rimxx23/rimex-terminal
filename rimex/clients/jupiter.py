import asyncio

import aiohttp

from rimex.domain.trading import Asset, CASH_SCALE, SIZE_SCALE, other_asset


ORDER_URL = "https://api.jup.ag/swap/v2/order"
MINTS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}
NATIVE_PER_UNIT = {"SOL": 10**9 // SIZE_SCALE, "USDT": 10**6 // CASH_SCALE}


class QuoteUnavailable(ValueError):
    pass


class JupiterQuotes:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = "") -> None:
        self.session = session
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.spacing = 0.3 if api_key else 2.1
        self.lock = asyncio.Lock()
        self.next_request = 0.0

    async def output(self, asset: Asset, amount: int) -> int:
        target = other_asset(asset)
        raw_input = amount * NATIVE_PER_UNIT[asset]
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(11):
                async with self.lock:
                    await asyncio.sleep(max(0, self.next_request - loop.time()))
                    self.next_request = loop.time() + self.spacing
                    async with self.session.get(
                        ORDER_URL,
                        params={"inputMint": MINTS[asset], "outputMint": MINTS[target], "amount": str(raw_input)},
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=7),
                    ) as response:
                        response.raise_for_status()
                        quote = await response.json()
            if int(quote["inAmount"]) != raw_input:
                raise ValueError("Unexpected quote input")
            raw_output = int(quote["outAmount"])
            rounded = raw_output // NATIVE_PER_UNIT[target]
            if not 0 < rounded <= 100_000_000_000:
                raise ValueError("Output is outside demo precision or limits")
            return rounded
        except (aiohttp.ClientError, OSError, ValueError, TypeError, KeyError, OverflowError):
            raise QuoteUnavailable("Jupiter could not quote this amount. Try again shortly.") from None
