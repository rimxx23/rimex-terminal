from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

RiskLevel = Literal["safe", "warning", "danger"]


@dataclass
class TokenReport:
    address: str
    symbol: str | None = None
    name: str | None = None
    price_usd: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None
    market_source: str | None = None
    authorities_loaded: bool = False
    mint_authority: str | None = None
    freeze_authority: str | None = None
    lp_locked_pct: Decimal | None = None
    risk_score: int | None = None
    holders_count: int | None = None
    top10_holders_pct: Decimal | None = None
    risks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0
