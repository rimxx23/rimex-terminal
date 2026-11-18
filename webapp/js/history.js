import { SOLANA_ADDRESS_RE } from "./levels.js";

export const HISTORY_KEY = "scan_history_v1";
export const HISTORY_LIMIT = 10;
const VERDICT_LEVELS = new Set(["danger", "warning", "safe", "unknown"]);

function sanitize(entry) {
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.address !== "string" || !SOLANA_ADDRESS_RE.test(entry.address)) return null;
  return {
    address: entry.address,
    symbol: typeof entry.symbol === "string" ? entry.symbol.slice(0, 32) : null,
    verdict: VERDICT_LEVELS.has(entry.verdict) ? entry.verdict : "unknown",
    scannedAt: Number.isFinite(entry.scannedAt) ? entry.scannedAt : 0,
  };
}

export function parseHistory(raw) {
  try {
    const items = JSON.parse(raw || "[]");
    if (!Array.isArray(items)) return [];
    return items.map(sanitize).filter(Boolean).slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

export function addEntry(entries, entry) {
  const clean = sanitize(entry);
  if (!clean) return entries;
  const rest = entries.filter((item) => item.address !== clean.address);
  return [clean, ...rest].slice(0, HISTORY_LIMIT);
}

export function createHistory(storage) {
  return {
    async load() {
      return parseHistory(await storage.getItem(HISTORY_KEY));
    },
    async add(entry) {
      const entries = addEntry(await this.load(), entry);
      await storage.setItem(HISTORY_KEY, JSON.stringify(entries));
      return entries;
    },
    async clear() {
      await storage.setItem(HISTORY_KEY, "[]");
      return [];
    },
  };
}


export function createBrowserStorage() {
  const memory = new Map();
  return {
    async getItem(key) {
      try {
        return window.localStorage.getItem(key);
      } catch {
        return memory.get(key) ?? null;
      }
    },
    async setItem(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        memory.set(key, value);
      }
    },
  };
}
