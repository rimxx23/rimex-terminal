from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel

from rimex.domain.known_tokens import find_known_token
from rimex.domain.models import RiskLevel, TokenReport
from rimex.domain.risk import (
    assess_honeypot,
    dev_holding_risk_level,
    lp_risk_level,
    pool_age_risk_level,
    top10_risk_level,
)


class ScanRequest(BaseModel):
    address: str


class ScanResponse(BaseModel):
    address: str
    symbol: str | None
    name: str | None
    known_issuer: str | None
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    volume_24h: Decimal | None
    market_source: str | None
    pool_created_at: datetime | None
    pool_age_level: RiskLevel | None
    authorities_loaded: bool
    mint_authority: str | None
    freeze_authority: str | None
    token_program: str | None
    transfer_fee_bps: int | None
    transfer_fee_mutable: bool
    transfer_hook_program: str | None
    permanent_delegate: str | None
    gt_honeypot: bool | None
    honeypot_level: RiskLevel | None
    honeypot_reasons: list[str]
    lp_locked_pct: Decimal | None
    lp_level: RiskLevel | None
    risk_score: int | None
    holders_count: int | None
    top10_holders_pct: Decimal | None
    top10_level: RiskLevel | None
    developer_address: str | None
    developer_holding_pct: Decimal | None
    dev_level: RiskLevel | None
    risks: list[str]
    errors: list[str]
    elapsed: float

    @classmethod
    def from_report(cls, report: TokenReport, now: datetime | None = None) -> "ScanResponse":
        honeypot = assess_honeypot(report)
        known = find_known_token(report.address)
        return cls(
            **asdict(report),
            known_issuer=known.issuer if known else None,
            pool_age_level=pool_age_risk_level(report.pool_created_at, now or datetime.now(UTC)),
            honeypot_level=honeypot.level,
            honeypot_reasons=honeypot.reasons,
            lp_level=lp_risk_level(report.lp_locked_pct),
            top10_level=top10_risk_level(report.top10_holders_pct),
            dev_level=dev_holding_risk_level(report.developer_holding_pct),
        )
