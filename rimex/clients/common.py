import asyncio
import ssl
from decimal import Decimal

import aiohttp
import certifi

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=3)


def create_http_session() -> aiohttp.ClientSession:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    return aiohttp.ClientSession(connector=connector, timeout=REQUEST_TIMEOUT)


def to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def describe_error(error: BaseException) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "no response in time (timeout)"
    if isinstance(error, aiohttp.ClientResponseError):
        if 400 <= error.status < 500:
            return f"request rejected (HTTP {error.status})"
        return f"server error (HTTP {error.status})"
    return f"connection error ({type(error).__name__})"
