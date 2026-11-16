from dataclasses import asdict
from decimal import Decimal

from pydantic import BaseModel

from rimex.domain.models import RiskLevel, TokenReport
from rimex.domain.risk import lp_risk_level, top10_risk_level


class ScanRequest(BaseModel):
    address: str


class ScanResponse(BaseModel):
    address: str
    symbol: str | None
    name: str | None
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    volume_24h: Decimal | None
    market_source: str | None
    authorities_loaded: bool
    mint_authority: str | None
    freeze_authority: str | None
    lp_locked_pct: Decimal | None
    lp_level: RiskLevel | None
    risk_score: int | None
    holders_count: int | None
    top10_holders_pct: Decimal | None
    top10_level: RiskLevel | None
    risks: list[str]
    errors: list[str]
    elapsed: float

    @classmethod
    def from_report(cls, report: TokenReport) -> "ScanResponse":
        return cls(
            **asdict(report),
            lp_level=lp_risk_level(report.lp_locked_pct),
            top10_level=top10_risk_level(report.top10_holders_pct),
        )
