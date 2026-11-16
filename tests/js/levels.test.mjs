import assert from "node:assert/strict";
import { test } from "node:test";

import { computeVerdict, devLevel, poolAgeLevel, top10Level } from "../../webapp/js/levels.js";

const NOW = Date.UTC(2026, 10, 16, 12);
const HOUR = 3600e3;
const USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

const cleanReport = {
  address: "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
  authorities_loaded: true,
  mint_authority: null,
  freeze_authority: null,
  honeypot_level: "safe",
  lp_level: null,
  top10_level: "safe",
  dev_level: "safe",
  pool_age_level: "safe",
};

test("pool age thresholds match the Python domain rules", () => {
  assert.equal(poolAgeLevel(NOW - 23 * HOUR, NOW), "danger");
  assert.equal(poolAgeLevel(NOW - 24 * HOUR, NOW), "warning");
  assert.equal(poolAgeLevel(NOW - 7 * 24 * HOUR, NOW), "safe");
});

test("developer and top 10 thresholds match the Python domain rules", () => {
  assert.deepEqual([4.99, 5, 19.99, 20].map(devLevel), ["safe", "warning", "warning", "danger"]);
  assert.deepEqual([34.99, 35, 69.99, 70].map(top10Level), ["safe", "warning", "warning", "danger"]);
});

test("clean token has no red flags", () => {
  const verdict = computeVerdict(cleanReport);

  assert.equal(verdict.level, "safe");
  assert.equal(verdict.title, "No red flags found");
  assert.deepEqual(verdict.reasons, []);
});

test("red flags win over warnings and are listed as reasons", () => {
  const verdict = computeVerdict({
    ...cleanReport,
    freeze_authority: "Freeze111",
    top10_holders_pct: "85.8",
    top10_level: "danger",
    dev_level: "warning",
    developer_holding_pct: "7",
  });

  assert.equal(verdict.level, "danger");
  assert.equal(verdict.redFlags, 2);
  assert.equal(verdict.warnings, 1);
  assert.deepEqual(verdict.reasons, ["freeze authority enabled", "top 10 hold 86%"]);
});

test("known issuer authorities are warnings, not red flags", () => {
  const verdict = computeVerdict({
    ...cleanReport,
    address: USDC,
    known_issuer: "Circle",
    mint_authority: "Mint111",
    freeze_authority: "Freeze111",
    honeypot_level: "warning",
  });

  assert.equal(verdict.level, "warning");
  assert.equal(verdict.redFlags, 0);
});

test("missing RPC data gives an unknown verdict, never safe", () => {
  const verdict = computeVerdict({ ...cleanReport, authorities_loaded: false, honeypot_level: null });

  assert.equal(verdict.level, "unknown");
});
