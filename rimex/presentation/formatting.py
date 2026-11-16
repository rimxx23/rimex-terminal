from datetime import UTC, datetime
from decimal import Decimal

from rimex.domain.known_tokens import find_known_token
from rimex.domain.models import RiskLevel, TokenReport
from rimex.domain.risk import (
    assess_honeypot,
    dev_holding_risk_level,
    lp_risk_level,
    pool_age_risk_level,
    top10_risk_level,
)

LEVEL_MARKS: dict[RiskLevel, str] = {"safe": "🟢", "warning": "🟡", "danger": "🔴"}


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "—"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.10f}".rstrip("0")


def format_authority(value: str | None, loaded: bool) -> str:
    if not loaded:
        return "⚪ unknown"
    if value is None:
        return "🟢 disabled"
    return f"🔴 enabled ({value[:4]}…{value[-4:]})"


def _format_pct(value: Decimal | None, level: RiskLevel | None) -> str:
    if value is None or level is None:
        return "—"
    return f"{LEVEL_MARKS[level]} {value:.1f}%"


def format_lp(value: Decimal | None) -> str:
    return _format_pct(value, lp_risk_level(value))


def format_top10(value: Decimal | None) -> str:
    return _format_pct(value, top10_risk_level(value))


def format_holders_count(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


HONEYPOT_LABELS: dict[RiskLevel, str] = {
    "safe": "no sell restrictions found",
    "warning": "possible sell restrictions",
    "danger": "sell restrictions",
}


def format_honeypot(report: TokenReport) -> str:
    assessment = assess_honeypot(report)
    if assessment.level is None:
        return "—"
    return f"{LEVEL_MARKS[assessment.level]} {HONEYPOT_LABELS[assessment.level]}"


def honeypot_reasons(report: TokenReport) -> list[str]:
    return assess_honeypot(report).reasons


def format_dev_holding(value: Decimal | None) -> str:
    return _format_pct(value, dev_holding_risk_level(value))


def human_age(created_at: datetime, now: datetime) -> str:
    minutes = int((now - created_at).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    if days < 60:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days / 365:.1f}y"


def format_pool_age(created_at: datetime | None, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    level = pool_age_risk_level(created_at, now)
    if created_at is None or level is None:
        return "—"
    return f"{LEVEL_MARKS[level]} {human_age(created_at, now)}"


def format_known_token(address: str) -> str | None:
    known = find_known_token(address)
    if known is None:
        return None
    return f"✅ Known token: {known.symbol} by {known.issuer}"
