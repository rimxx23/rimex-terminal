export function formatMoney(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (number >= 1) {
    return "$" + number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return "$" + String(value).replace(/0+$/, "");
}

export function formatPct(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(1)}%`;
}

export function formatCount(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-US");
}

export function humanAge(date, now = Date.now()) {
  const minutes = Math.floor((now - new Date(date).getTime()) / 60000);
  if (minutes < 60) return `${Math.max(minutes, 0)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 60) return `${days}d`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

export function shortAddress(address) {
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

export function initials(user) {
  const source = user?.first_name || user?.username || "?";
  return source.trim().slice(0, 1).toUpperCase() || "?";
}
