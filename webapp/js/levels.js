const HOUR_MS = 60 * 60 * 1000;

export const THRESHOLDS = {
  poolAgeDangerMs: 24 * HOUR_MS,
  poolAgeWarningMs: 7 * 24 * HOUR_MS,
  devWarningPct: 5,
  devDangerPct: 20,
  top10WarningPct: 35,
  top10DangerPct: 70,
};

export const SOLANA_ADDRESS_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

export function poolAgeLevel(date, now = Date.now()) {
  const age = now - new Date(date).getTime();
  if (age < THRESHOLDS.poolAgeDangerMs) return "danger";
  if (age < THRESHOLDS.poolAgeWarningMs) return "warning";
  return "safe";
}

export function devLevel(pct) {
  if (pct >= THRESHOLDS.devDangerPct) return "danger";
  if (pct >= THRESHOLDS.devWarningPct) return "warning";
  return "safe";
}

export function top10Level(pct) {
  if (pct >= THRESHOLDS.top10DangerPct) return "danger";
  if (pct >= THRESHOLDS.top10WarningPct) return "warning";
  return "safe";
}

function authorityLevel(value, loaded, knownIssuer) {
  if (!loaded || value === null || value === undefined) return null;
  return knownIssuer ? "warning" : "danger";
}

export function collectSignals(report) {
  const known = Boolean(report.known_issuer);
  return [
    { label: "mint authority enabled", level: authorityLevel(report.mint_authority, report.authorities_loaded, known) },
    { label: "freeze authority enabled", level: authorityLevel(report.freeze_authority, report.authorities_loaded, known) },
    { label: "honeypot signs", level: report.honeypot_level },
    { label: `LP locked ${formatShortPct(report.lp_locked_pct)}`, level: report.lp_level },
    { label: `top 10 hold ${formatShortPct(report.top10_holders_pct)}`, level: report.top10_level },
    { label: `developer holds ${formatShortPct(report.developer_holding_pct)}`, level: report.dev_level },
    { label: "new pool", level: report.pool_age_level },
  ].filter((signal) => signal.level === "danger" || signal.level === "warning");
}

function formatShortPct(value) {
  return value === null || value === undefined ? "?" : `${Math.round(Number(value))}%`;
}

export const VERDICT_TITLES = {
  danger: "High risk",
  warning: "Caution",
  safe: "No red flags found",
  unknown: "Not enough data",
};

export function computeVerdict(report) {
  const signals = collectSignals(report);
  const red = signals.filter((signal) => signal.level === "danger");
  const yellow = signals.filter((signal) => signal.level === "warning");
  let level = "safe";
  if (red.length) level = "danger";
  else if (yellow.length) level = "warning";
  else if (!report.authorities_loaded) level = "unknown";
  return {
    level,
    title: VERDICT_TITLES[level],
    redFlags: red.length,
    warnings: yellow.length,
    reasons: (red.length ? red : yellow).map((signal) => signal.label),
  };
}
