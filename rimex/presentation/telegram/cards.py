import html

from rimex.domain.address import short_address
from rimex.domain.models import TokenReport
from rimex.presentation.formatting import (
    format_holders_count,
    format_honeypot,
    format_lp,
    format_money,
    format_top10,
    honeypot_reasons,
)


def format_authority_html(value: str | None, loaded: bool) -> str:
    if not loaded:
        return "⚪ unknown"
    if value is None:
        return "🟢 disabled"
    return f"🔴 <b>enabled</b> (<code>{value[:4]}…{value[-4:]}</code>)"


def format_card(report: TokenReport) -> str:
    symbol = html.escape(report.symbol or "?")
    name = html.escape(report.name or "?")
    risk = report.risk_score if report.risk_score is not None else "—"
    lines = [
        f"<b>{symbol}</b> · {name}",
        f"<code>{report.address}</code>",
        "",
        f"💵 Price: <b>{format_money(report.price_usd)}</b>",
        f"💧 Liquidity: {format_money(report.liquidity_usd)}",
        f"📊 Volume 24h: {format_money(report.volume_24h)}",
        "",
        "<b>X-Ray security</b>",
        f"Mint Authority: {format_authority_html(report.mint_authority, report.authorities_loaded)}",
        f"Freeze Authority: {format_authority_html(report.freeze_authority, report.authorities_loaded)}",
        f"Honeypot: {format_honeypot(report)}",
        f"LP locked: {format_lp(report.lp_locked_pct)}",
        f"Top 10 holders: {format_top10(report.top10_holders_pct)}",
        f"Holders: {format_holders_count(report.holders_count)}",
        f"RugCheck risk: {risk} (lower is safer)",
    ]
    lines.extend(f"  · {html.escape(reason)}" for reason in honeypot_reasons(report))
    if report.risks:
        lines.append(f"Risks: {html.escape(', '.join(report.risks))}")
    if report.errors:
        lines.append("")
        lines.extend(f"⚠️ {html.escape(error)}" for error in report.errors)
    lines.append("")
    source = f" · market data: {html.escape(report.market_source)}" if report.market_source else ""
    lines.append(f"<i>Scanned in {report.elapsed:.2f}s{source}</i>")
    return "\n".join(lines)


def format_open_app_message(address: str) -> str:
    return (
        f"<b>Token</b> <code>{short_address(address)}</code>\n\n"
        "Tap <b>🔍 Open in X-Ray</b> to see price, liquidity, "
        "Mint/Freeze authority, honeypot signs, LP lock and top holders."
    )


START_MESSAGE = (
    "<b>Rimex X-Ray</b>\n\n"
    "Send me a Solana token contract address and open it in X-Ray:\n"
    "price, liquidity, Mint/Freeze authority, honeypot signs, LP lock and top holders."
)
