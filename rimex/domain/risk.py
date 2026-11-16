from decimal import Decimal

from rimex.domain.models import RiskLevel

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
