import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, scanToken } from "../../webapp/js/api.js";
import { fillMissingData } from "../../webapp/js/fallback.js";
import { formatMoney, humanAge, initials, shortAddress } from "../../webapp/js/format.js";

const ADDRESS = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN";

const jsonResponse = (body, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => body,
});

function fakeFetch(routes) {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    const route = Object.keys(routes).find((prefix) => url.startsWith(prefix));
    if (!route) throw new Error(`unexpected request ${url}`);
    return routes[route]();
  };
  return { fetchImpl, calls };
}

const emptyServerReport = {
  address: ADDRESS,
  market_source: null,
  authorities_loaded: true,
  top10_holders_pct: null,
  errors: ["DexScreener: request rejected (HTTP 429)", "GeckoTerminal: request rejected (HTTP 429)", "Holders: request rejected (HTTP 429)"],
};

test("fills market and holders from the device and clears their errors", async () => {
  const { fetchImpl, calls } = fakeFetch({
    "https://api.dexscreener.com": () => jsonResponse([{ baseToken: { symbol: "JUP", name: "Jupiter" }, priceUsd: "0.26", liquidity: { usd: 450000 } }]),
    "https://api.geckoterminal.com": () => jsonResponse({ data: { attributes: { holders: { count: 828512, distribution_percentage: { top_10: "64.6" } }, developer_holding_percentage: "0.0" } } }),
  });

  const filled = await fillMissingData(emptyServerReport, fetchImpl);

  assert.equal(filled.symbol, "JUP");
  assert.equal(filled.market_source, "DexScreener (direct)");
  assert.equal(filled.top10_level, "warning");
  assert.equal(filled.dev_level, "safe");
  assert.deepEqual(filled.errors, []);
  assert.equal(calls.length, 2, "authorities were loaded by the server, so RPC is not called");
});

test("keeps server errors when the device request also fails", async () => {
  const { fetchImpl } = fakeFetch({
    "https://api.dexscreener.com": () => jsonResponse({}, 429),
    "https://api.geckoterminal.com": () => jsonResponse({}, 429),
  });

  const filled = await fillMissingData(emptyServerReport, fetchImpl);

  assert.equal(filled.symbol, undefined);
  assert.equal(filled.errors.length, 3);
});

test("nothing is requested when the server already has everything", async () => {
  const { fetchImpl, calls } = fakeFetch({});

  await fillMissingData({ ...emptyServerReport, market_source: "DexScreener", top10_holders_pct: "10", errors: [] }, fetchImpl);

  assert.equal(calls.length, 0);
});

test("scanToken uses the website endpoint and returns the report", async () => {
  let sent;
  const fetchImpl = async (url, options) => {
    sent = { url, options };
    return jsonResponse({ address: ADDRESS });
  };

  const report = await scanToken(ADDRESS, fetchImpl);

  assert.equal(report.address, ADDRESS);
  assert.equal(sent.url, "/api/web/scan");
  assert.deepEqual(sent.options.headers, { "Content-Type": "application/json" });
});

test("scanToken turns API errors into readable messages", async () => {
  await assert.rejects(
    scanToken(ADDRESS, async () => jsonResponse({ detail: "Too many requests. Try again in 30s" }, 429)),
    (error) => error instanceof ApiError && error.message === "Too many requests. Try again in 30s"
  );
  await assert.rejects(
    scanToken(ADDRESS, async () => { throw new TypeError("offline"); }),
    (error) => error instanceof ApiError && error.message === "Network error. Try again."
  );
});

test("formatting helpers", () => {
  const now = Date.UTC(2026, 10, 16, 12);
  assert.equal(formatMoney(null), "—");
  assert.equal(formatMoney("1234.5"), "$1,234.50");
  assert.equal(formatMoney("0.000002350"), "$0.00000235");
  assert.equal(humanAge(now - 5 * 3600e3, now), "5h");
  assert.equal(shortAddress(ADDRESS), "JUPy…DvCN");
  assert.equal(initials({ first_name: "alex" }), "A");
  assert.equal(initials(null), "?");
});
