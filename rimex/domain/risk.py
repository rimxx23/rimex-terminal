from dataclasses import dataclass, field
from decimal import Decimal

from rimex.domain.models import RiskLevel, TokenReport

LP_SAFE_PCT = Decimal("90")
LP_WARNING_PCT = Decimal("50")
TOP10_WARNING_PCT = Decimal("35")
TOP10_DANGER_PCT = Decimal("70")


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


TRANSFER_FEE_DANGER_BPS = 1000


@dataclass
class HoneypotAssessment:
    level: RiskLevel | None
    reasons: list[str] = field(default_factory=list)


def assess_honeypot(report: TokenReport) -> HoneypotAssessment:
    danger = []
    warning = []

    if report.gt_honeypot:
        danger.append("flagged as honeypot by GeckoTerminal")
    if report.transfer_hook_program:
        danger.append("transfer hook can block selling")
    if report.permanent_delegate:
        danger.append("permanent delegate can move tokens from any wallet")
    if report.authorities_loaded and report.freeze_authority:
        danger.append("freeze authority can freeze your tokens")

    fee = report.transfer_fee_bps or 0
    if fee >= TRANSFER_FEE_DANGER_BPS:
        danger.append(f"transfer fee {fee / 100:g}%")
    elif fee > 0:
        warning.append(f"transfer fee {fee / 100:g}%")
    if report.transfer_fee_mutable:
        warning.append("transfer fee can be raised")

    if danger:
        return HoneypotAssessment("danger", danger + warning)
    if warning:
        return HoneypotAssessment("warning", warning)
    if report.authorities_loaded:
        return HoneypotAssessment("safe")
    return HoneypotAssessment(None)
