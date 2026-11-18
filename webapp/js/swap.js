import { loginPage, prepareSession, webRequest } from "./session.js";

const byId = (id) => document.getElementById(id);
const form = byId("swap-form");
const amount = byId("swap-amount");
const direction = byId("swap-direction");
const getQuote = byId("get-quote");
const confirmSwap = byId("confirm-swap");
const time = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const limits = {
  SOL: { step: "0.001", max: "1000", digits: 3 },
  USDT: { step: "0.00001", max: "100000", digits: 5 },
};
let asset = new URLSearchParams(location.search).get("from") === "USDT" ? "USDT" : "SOL";
let quote = null;
let balances;
let busy = false;

const opposite = () => asset === "SOL" ? "USDT" : "SOL";

function number(value, currency) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: limits[currency].digits }).format(Number(value));
}

function message(text = "", error = false) {
  const status = byId("swap-status");
  status.textContent = text;
  status.dataset.error = String(error);
}

async function api(path = "", method = "GET", body) {
  const response = await webRequest(`/api/swap${path}`, method, body);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) loginPage();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "Check the amount and try again.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function updateForm() {
  const { step, max } = limits[asset];
  amount.step = amount.min = step;
  amount.max = max;
  byId("input-asset").textContent = asset;
  byId("output-asset").textContent = opposite();
  byId("available").textContent = balances ? `Available ${number(balances[asset], asset)} ${asset}` : "Available —";
  amount.disabled = direction.disabled = getQuote.disabled = busy;
  confirmSwap.hidden = !quote;
  confirmSwap.disabled = busy;
}

function updateQuote() {
  byId("swap-details").hidden = !quote;
  byId("expected-output").textContent = quote ? number(quote.expected_output, quote.output_asset) : "—";
  if (quote) {
    const rate = Number(quote.expected_output) / Number(quote.input_amount);
    const displayedRate = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 7 }).format(rate);
    byId("swap-rate").textContent = `1 ${quote.input_asset} ≈ ${displayedRate} ${quote.output_asset}`;
    byId("swap-slippage").textContent = `${quote.slippage_bps / 100}%`;
    byId("min-output").textContent = `${number(quote.min_output, quote.output_asset)} ${quote.output_asset}`;
  }
  updateForm();
  updateTimer();
}

function updateTimer() {
  if (!quote) return;
  const seconds = Math.max(0, Math.ceil(quote.expires_at - Date.now() / 1000));
  byId("quote-timer").textContent = `${seconds}s`;
  confirmSwap.disabled = busy || seconds === 0;
  if (!seconds && !busy) {
    quote = null;
    updateQuote();
    message("Quote expired. Get a new quote.", true);
  }
}

async function refreshWallet() {
  const result = await api();
  balances = result.balances;
  byId("swap-sol").textContent = number(balances.SOL, "SOL");
  byId("swap-usdt").textContent = number(balances.USDT, "USDT");
  const history = byId("swap-history");
  const rows = result.history.map((item) => {
    const row = document.createElement("tr");
    for (const value of [
      `${number(item.input_amount, item.input_asset)} ${item.input_asset}`,
      `${number(item.output_amount, item.output_asset)} ${item.output_asset}`,
      time.format(item.executed_at * 1000),
    ]) {
      row.insertCell().textContent = value;
    }
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = row.insertCell();
    cell.colSpan = 3;
    cell.className = "table-empty";
    cell.textContent = "No swaps yet";
    rows.push(row);
  }
  history.replaceChildren(...rows);
  updateForm();
}

function clearQuote() {
  quote = null;
  updateQuote();
  message();
}

direction.addEventListener("click", () => {
  asset = opposite();
  amount.value = "";
  clearQuote();
  amount.focus();
});
amount.addEventListener("input", clearQuote);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  quote = null;
  updateQuote();
  message("Getting a Jupiter quote…");
  try {
    quote = await api("/quotes", "POST", { asset, amount: amount.value });
    message();
  } catch (error) {
    message(error.message, true);
  } finally {
    busy = false;
    updateQuote();
  }
});

confirmSwap.addEventListener("click", async () => {
  if (!quote || busy) return;
  busy = true;
  updateForm();
  message("Checking the price and balance…");
  try {
    const receipt = await api(`/quotes/${quote.id}/confirm`, "POST");
    quote = null;
    amount.value = "";
    const paid = `${number(receipt.input_amount, receipt.input_asset)} ${receipt.input_asset}`;
    const received = `${number(receipt.output_amount, receipt.output_asset)} ${receipt.output_asset}`;
    await refreshWallet().catch(() => {
      balances = undefined;
      byId("swap-sol").textContent = byId("swap-usdt").textContent = "—";
    });
    message(`Swapped ${paid} for ${received}.`);
  } catch (error) {
    if ([404, 409].includes(error.status)) quote = null;
    message(error.message, true);
  } finally {
    busy = false;
    updateQuote();
  }
});

async function start() {
  try {
    if (!await prepareSession()) return;
    document.querySelector(".swap-terminal").hidden = false;
    updateForm();
    await refreshWallet();
  } catch (error) {
    const status = byId("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
  }
}
setInterval(updateTimer, 1000);
start();
