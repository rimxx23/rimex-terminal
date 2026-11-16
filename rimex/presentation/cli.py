import sys

from rimex.domain.models import TokenReport
from rimex.presentation.formatting import (
    format_authority,
    format_holders_count,
    format_honeypot,
    format_lp,
    format_money,
    format_top10,
    honeypot_reasons,
)
from rimex.services.scanner import scan_solana_token


def format_report(report: TokenReport) -> str:
    risk = report.risk_score if report.risk_score is not None else "—"
    lines = [
        f"Token:          {report.symbol or '?'} ({report.name or '?'})",
        f"Address:        {report.address}",
        f"Price:          {format_money(report.price_usd)}",
        f"Liquidity:      {format_money(report.liquidity_usd)}",
        f"Volume 24h:     {format_money(report.volume_24h)}",
        f"Mint Authority: {format_authority(report.mint_authority, report.authorities_loaded)}",
        f"Freeze Auth.:   {format_authority(report.freeze_authority, report.authorities_loaded)}",
        f"Honeypot:       {format_honeypot(report)}",
        f"LP locked:      {format_lp(report.lp_locked_pct)}",
        f"Top 10 holders: {format_top10(report.top10_holders_pct)}",
        f"Holders:        {format_holders_count(report.holders_count)}",
        f"RugCheck risk:  {risk} (lower is safer)",
    ]
    for reason in honeypot_reasons(report):
        lines.append(f"  · {reason}")
    if report.risks:
        lines.append(f"Risks:          {', '.join(report.risks)}")
    for error in report.errors:
        lines.append(f"⚠️  {error}")
    lines.append(f"Scan time:      {report.elapsed:.2f}s")
    return "\n".join(lines)


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m rimex <token address>")
        sys.exit(1)
    report = await scan_solana_token(sys.argv[1])
    print(format_report(report))
