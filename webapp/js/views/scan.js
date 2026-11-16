import { el, setField } from "../dom.js";
import { formatCount, formatMoney, formatPct, humanAge } from "../format.js";
import { computeVerdict } from "../levels.js";

const HONEYPOT_LABELS = { safe: "not found", warning: "possible", danger: "sell restrictions" };

const EXTERNAL_LINKS = {
  DexScreener: (address) => `https://dexscreener.com/solana/${address}`,
  RugCheck: (address) => `https://rugcheck.xyz/tokens/${address}`,
  Solscan: (address) => `https://solscan.io/token/${address}`,
};

function authority(value, loaded) {
  if (!loaded) return ["unknown", "unknown"];
  if (value === null || value === undefined) return ["disabled", "safe"];
  return ["enabled", "danger"];
}

export function renderHint(container) {
  container.replaceChildren(
    el("div", { className: "hint" }, [
      "Paste a Solana token contract address",
      el("br"),
      "to check it in under a second.",
    ])
  );
}

export function renderMessage(container, text) {
  container.replaceChildren(el("div", { className: "error", text }));
}

export function renderLoading(container) {
  const rows = Array.from({ length: 6 }, () => el("div", { className: "skeleton-row" }));
  container.replaceChildren(
    el("div", { className: "skeleton" }, [el("div", { className: "skeleton-title" }), ...rows])
  );
}

function renderVerdict(view, verdict) {
  const banner = view.querySelector('[data-field="verdict"]');
  banner.classList.add(`verdict-${verdict.level}`);
  const counts = [];
  if (verdict.redFlags) counts.push(`${verdict.redFlags} red flag${verdict.redFlags > 1 ? "s" : ""}`);
  if (verdict.warnings) counts.push(`${verdict.warnings} warning${verdict.warnings > 1 ? "s" : ""}`);
  setField(view, "verdict-title", [verdict.title, ...counts].join(" · "));
  setField(view, "verdict-reasons", verdict.reasons.join(" · "));
}

function renderNotices(view, report) {
  const notices = view.querySelector('[data-field="notices"]');
  const lines = [
    ...(report.honeypot_reasons ?? []).map((reason) => `Honeypot: ${reason}`),
    ...(report.risks ?? []).map((risk) => `Risk: ${risk}`),
    ...(report.errors ?? []),
  ];
  notices.replaceChildren(...lines.map((line) => el("div", { className: "notice", text: `⚠ ${line}` })));
}

function renderLinks(view, address, onOpenLink) {
  const links = view.querySelector('[data-field="links"]');
  links.replaceChildren(
    ...Object.entries(EXTERNAL_LINKS).map(([title, build]) => {
      const url = build(address);
      return el("a", {
        text: title,
        attrs: { href: url },
        onClick: (event) => {
          event.preventDefault();
          onOpenLink(url);
        },
      });
    })
  );
}

export function renderReport(container, template, report, { onOpenLink, onCopy }) {
  const view = template.content.cloneNode(true);
  const verdict = computeVerdict(report);
  renderVerdict(view, verdict);

  setField(view, "symbol", report.symbol ?? "?");
  setField(view, "name", report.name ?? "Unknown token");
  setField(view, "known", report.known_issuer ? `✓ Known token · issuer: ${report.known_issuer}` : "");
  const address = setField(view, "address", report.address);
  address.addEventListener("click", () => onCopy(report.address));

  setField(view, "price", formatMoney(report.price_usd));
  setField(view, "liquidity", formatMoney(report.liquidity_usd));
  setField(view, "volume", formatMoney(report.volume_24h));
  setField(view, "pool-age", report.pool_created_at ? humanAge(report.pool_created_at) : "—", report.pool_age_level);

  setField(view, "mint", ...authority(report.mint_authority, report.authorities_loaded));
  setField(view, "freeze", ...authority(report.freeze_authority, report.authorities_loaded));
  setField(view, "honeypot", report.honeypot_level ? HONEYPOT_LABELS[report.honeypot_level] : "—", report.honeypot_level);
  setField(view, "lp", formatPct(report.lp_locked_pct), report.lp_level);
  setField(view, "top10", formatPct(report.top10_holders_pct), report.top10_level);
  setField(view, "holders", formatCount(report.holders_count));
  setField(view, "dev", formatPct(report.developer_holding_pct), report.dev_level);
  setField(view, "risk", report.risk_score === null || report.risk_score === undefined ? "—" : `${report.risk_score} (lower is safer)`);

  renderNotices(view, report);
  renderLinks(view, report.address, onOpenLink);

  const source = report.market_source ? ` · market data: ${report.market_source}` : "";
  setField(view, "elapsed", `Scanned in ${Number(report.elapsed ?? 0).toFixed(2)}s${source}`);

  container.replaceChildren(view);
  return verdict;
}
