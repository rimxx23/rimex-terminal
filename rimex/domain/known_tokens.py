from dataclasses import dataclass


@dataclass(frozen=True)
class KnownToken:
    symbol: str
    issuer: str


KNOWN_TOKENS: dict[str, KnownToken] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": KnownToken("USDC", "Circle"),
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": KnownToken("USDT", "Tether"),
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": KnownToken("PYUSD", "Paxos for PayPal"),
}


def find_known_token(address: str) -> KnownToken | None:
    return KNOWN_TOKENS.get(address)
