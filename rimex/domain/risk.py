from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from rimex.domain.known_tokens import find_known_token
from rimex.domain.models import RiskLevel, TokenReport

LP_SAFE_PCT = Decimal("90")
LP_WARNING_PCT = Decimal("50")
TOP10_WARNING_PCT = Decimal("35")
TOP10_DANGER_PCT = Decimal("70")
DEV_HOLDING_WARNING_PCT = Decimal("5")
DEV_HOLDING_DANGER_PCT = Decimal("20")
POOL_AGE_DANGER = timedelta(days=1)
POOL_AGE_WARNING = timedelta(days=7)


def lp_risk_level(value: Decimal | None) -> RiskLevel | None:
    if value is None:
        return None
    if value >= LP_SAFE_PCT:
        return "safe"
    if value >= LP_WARNING_PCT:
        return "warning"
    return "danger"


def top10_risk_level(value: Decimal | None) -> RiskLevel | None:
    if value is None:
        return None
    if value >= TOP10_DANGER_PCT:
        return "danger"
    if value >= TOP10_WARNING_PCT:
        return "warning"
    return "safe"


def dev_holding_risk_level(value: Decimal | None) -> RiskLevel | None:
    if value is None:
        return None
    if value >= DEV_HOLDING_DANGER_PCT:
        return "danger"
    if value >= DEV_HOLDING_WARNING_PCT:
        return "warning"
    return "safe"


def pool_age_risk_level(created_at: datetime | None, now: datetime) -> RiskLevel | None:
    if created_at is None:
        return None
    age = now - created_at
    if age < POOL_AGE_DANGER:
        return "danger"
    if age < POOL_AGE_WARNING:
        return "warning"
    return "safe"


TRANSFER_FEE_DANGER_BPS = 1000


@dataclass
class HoneypotAssessment:
    level: RiskLevel | None
    reasons: list[str] = field(default_factory=list)


def assess_honeypot(report: TokenReport) -> HoneypotAssessment:
    danger = []
    warning = []
    issuer_danger = []
    issuer_warning = []

    if report.gt_honeypot:
        danger.append("flagged as honeypot by GeckoTerminal")
    if report.transfer_hook_program:
        danger.append("transfer hook can block selling")

    fee = report.transfer_fee_bps or 0
    if fee >= TRANSFER_FEE_DANGER_BPS:
        danger.append(f"transfer fee {fee / 100:g}%")
    elif fee > 0:
        warning.append(f"transfer fee {fee / 100:g}%")

    if report.permanent_delegate:
        issuer_danger.append("permanent delegate can move tokens from any wallet")
    if report.authorities_loaded and report.freeze_authority:
        issuer_danger.append("freeze authority can freeze your tokens")
    if report.transfer_fee_mutable:
        issuer_warning.append("transfer fee can be raised")

    known = find_known_token(report.address)
    if known and (issuer_danger or issuer_warning):
        warning.append(f"regulated issuer ({known.issuer}) can freeze or move tokens")
    else:
        danger.extend(issuer_danger)
        warning.extend(issuer_warning)

    if danger:
        return HoneypotAssessment("danger", danger + warning)
    if warning:
        return HoneypotAssessment("warning", warning)
    if report.authorities_loaded:
        return HoneypotAssessment("safe")
    return HoneypotAssessment(None)
