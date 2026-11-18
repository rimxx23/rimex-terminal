import asyncio
import logging
import time
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_FLOOR

import aiohttp

from rimex.domain.trading import PRICE_SCALE


SYMBOL = "SOLUSDT"
WEBSOCKET = "wss://data-stream.binance.vision/ws/solusdt@bookTicker"
BOOK_TICKER = "https://data-api.binance.vision/api/v3/ticker/bookTicker"
KLINES = "https://data-api.binance.vision/api/v3/klines"
CANDLE_INTERVALS = {"1m": 60, "5m": 300, "15m": 900}
logger = logging.getLogger(__name__)


def parse_quote(bid: str, ask: str) -> tuple[int, int]:
    low = Decimal(bid) * PRICE_SCALE
    high = Decimal(ask) * PRICE_SCALE
    if not low.is_finite() or not high.is_finite() or not 0 < low < high:
        raise ValueError("Invalid market quote")
    return int(low.to_integral_value(rounding=ROUND_FLOOR)), int(high.to_integral_value(rounding=ROUND_CEILING))


async def stream_quotes(session: aiohttp.ClientSession, on_quote) -> None:
    while True:
        try:
            async with asyncio.timeout(12):
                ws = await session.ws_connect(WEBSOCKET, heartbeat=20)
            async with ws:
                last_sent = 0.0
                while True:
                    data = await ws.receive_json(timeout=12)
                    now = time.monotonic()
                    if now - last_sent >= 1 and data.get("s") == SYMBOL:
                        await on_quote(*parse_quote(data["b"], data["a"]), "Binance WebSocket")
                        last_sent = now
        except (aiohttp.ClientError, OSError, ValueError, TypeError, KeyError, DecimalException):
            logger.debug("Binance WebSocket unavailable; using public REST snapshots", exc_info=True)

        # A short REST fallback also allows regions/networks that limit WebSockets.
        for _ in range(4):
            try:
                async with session.get(
                    BOOK_TICKER, params={"symbol": SYMBOL}, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    await on_quote(*parse_quote(data["bidPrice"], data["askPrice"]), "Binance REST")
            except (aiohttp.ClientError, OSError, ValueError, TypeError, KeyError, DecimalException):
                logger.debug("Binance snapshot unavailable", exc_info=True)
            await asyncio.sleep(3)


async def fetch_candles(session: aiohttp.ClientSession, interval: str) -> list[dict]:
    async with session.get(
        KLINES, params={"symbol": SYMBOL, "interval": interval, "limit": 96},
        timeout=aiohttp.ClientTimeout(total=6),
    ) as response:
        response.raise_for_status()
        rows = await response.json()

    candles = []
    for row in rows:
        prices = [Decimal(row[index]) for index in range(1, 5)]
        if any(not price.is_finite() or price <= 0 for price in prices):
            raise ValueError("Invalid market candle")
        candles.append({
            "time": int(row[0]) // 1000,
            "open": str(prices[0]),
            "high": str(prices[1]),
            "low": str(prices[2]),
            "close": str(prices[3]),
        })
    if not candles:
        raise ValueError("Empty market candle response")
    return candles
