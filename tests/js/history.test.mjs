import assert from "node:assert/strict";
import { test } from "node:test";

import { HISTORY_KEY, HISTORY_LIMIT, addEntry, createHistory, parseHistory } from "../../webapp/js/history.js";

const address = (n) => `${"1".repeat(43)}${"ABCDEFGHJKLMNPQRSTUVWXYZ"[n]}`;

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    async getItem(key) {
      return data.get(key) ?? null;
    },
    async setItem(key, value) {
      data.set(key, value);
    },
  };
}

test("new scans go to the top and the list keeps only 10", () => {
  let entries = [];
  for (let i = 0; i < 12; i++) {
    entries = addEntry(entries, { address: address(i), symbol: `T${i}`, verdict: "safe", scannedAt: i });
  }

  assert.equal(entries.length, HISTORY_LIMIT);
  assert.equal(entries[0].symbol, "T11");
  assert.equal(entries.at(-1).symbol, "T2");
});

test("scanning the same token again moves it to the top without duplicates", () => {
  let entries = [];
  entries = addEntry(entries, { address: address(0), symbol: "A", verdict: "safe", scannedAt: 1 });
  entries = addEntry(entries, { address: address(1), symbol: "B", verdict: "safe", scannedAt: 2 });
  entries = addEntry(entries, { address: address(0), symbol: "A", verdict: "danger", scannedAt: 3 });

  assert.deepEqual(entries.map((entry) => entry.symbol), ["A", "B"]);
  assert.equal(entries[0].verdict, "danger");
});

test("broken or tampered storage data is ignored", () => {
  assert.deepEqual(parseHistory("not json"), []);
  assert.deepEqual(parseHistory('{"a":1}'), []);
  assert.deepEqual(parseHistory(null), []);

  const entries = parseHistory(JSON.stringify([
    { address: "<script>", symbol: "X", verdict: "safe" },
    { address: address(0), symbol: "Y".repeat(100), verdict: "hacked", scannedAt: "soon" },
  ]));

  assert.equal(entries.length, 1);
  assert.equal(entries[0].symbol.length, 32);
  assert.equal(entries[0].verdict, "unknown");
  assert.equal(entries[0].scannedAt, 0);
});

test("history is saved to and loaded from storage", async () => {
  const storage = memoryStorage();
  const history = createHistory(storage);

  await history.add({ address: address(0), symbol: "JUP", verdict: "safe", scannedAt: 1 });
  const reloaded = await createHistory(storage).load();

  assert.equal(reloaded[0].symbol, "JUP");
  assert.ok(storage.data.has(HISTORY_KEY));
});

test("clear empties the history", async () => {
  const history = createHistory(memoryStorage());
  await history.add({ address: address(0), symbol: "A", verdict: "safe", scannedAt: 1 });

  await history.clear();

  assert.deepEqual(await history.load(), []);
});
