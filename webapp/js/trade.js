import { ApiError } from "./api.js";
import { createTradeChart } from "./chart.js?v=9";
import { loginPage, prepareSession } from "./session.js";

const $ = (id) => document.getElementById(id);
const form = $("order-form");
const exitForm = $("exit-form");
const price = $("price");
const size = $("size");
const asPrice = (value) => Number(value).toFixed(2);
const asSize = (value) => Number(value).toFixed(3);
const asCash = (value) => Number(value).toFixed(5).replace(/(\.\d{2})0+$/, "$1");
const time = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });
const renderedRows = new Map();
let snapshot;
let writing = false;
let loading = false;
let latestRequest = 0;

const side = () => form.elements.side.value;
const kind = () => form.elements.kind.value;
const chart = createTradeChart((interval) => api(`/candles?interval=${interval}`));

const triggerLabels = { stop_loss: "Stop loss", take_profit: "Take profit" };

function notice(message, error = false, target = "trade-notice") {
  $(target).textContent = message;
  $(target).dataset.error = String(error);
}

async function api(path = "", method = "GET", payload) {
  const headers = { "X-Rimex-Trade": "1" };
  let body;
  if (payload) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(payload);
  }
  const response = await fetch(`/api/trade${path}`, { method, headers, body, cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) loginPage();
    throw new ApiError(typeof data.detail === "string" ? data.detail : "Check your price and amount.", response.status);
  }
  return data;
}

function cell(row, value, className = "") {
  const item = row.insertCell();
  item.textContent = value;
  item.className = className;
  return item;
}

function renderRows(target, list, width, empty, buildRow) {
  const signature = JSON.stringify(list);
  if (renderedRows.get(target) === signature) return;
  const rows = list.map((item) => {
    const row = document.createElement("tr");
    buildRow(row, item);
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr");
    cell(row, empty, "table-empty").colSpan = width;
    rows.push(row);
  }
  $(target).replaceChildren(...rows);
  renderedRows.set(target, signature);
}

function renderForm() {
  const direction = side();
  const marketOrder = kind() === "market";
  $("price-field").hidden = marketOrder;
  $("market-note").hidden = !marketOrder;
  price.disabled = marketOrder;
  $("total-label").textContent = marketOrder ? "Est. order value" : "Order value";
  const quote = direction === "buy" ? snapshot?.market?.ask : snapshot?.market?.bid;
  const value = Number(marketOrder ? quote : price.value) * Number(size.value);
  $("total").textContent = value > 0 ? `${asCash(value)} USDT` : "—";
  $("place").textContent = direction === "buy" ? "Place buy order" : "Place sell order";
  $("place").dataset.side = direction;
  $("place").disabled = !snapshot?.market || writing;
  $("protect-sol").disabled = !snapshot?.market || writing;
  $("best-price").disabled = !snapshot?.market;
}

function render({ market, wallet, book, orders, trades, exits }) {
  $("feed").dataset.live = String(Boolean(market));
  $("feed").textContent = market ? market.source : "Quote feed unavailable";
  $("bid").textContent = market ? asPrice(market.bid) : "—";
  $("ask").textContent = market ? asPrice(market.ask) : "—";
  $("cash").textContent = asCash(wallet.usdt);
  $("sol").textContent = asSize(wallet.sol);
  $("locked-cash").textContent = asCash(wallet.locked_usdt);
  $("locked-sol").textContent = asSize(wallet.locked_sol);

  for (const [direction, id] of [["buy", "bids"], ["sell", "asks"]]) {
    renderRows(id, book[direction], 2, "No orders at this side", (row, level) => {
      cell(row, asPrice(level.price), direction);
      cell(row, asSize(level.size));
    });
  }
  renderRows("orders", orders, 6, "No orders yet", (row, order) => {
    cell(row, order.side.toUpperCase(), order.side);
    cell(row, triggerLabels[order.kind] ?? (order.kind === "market" ? "Market" : asPrice(order.price)));
    cell(row, asSize(order.size));
    cell(row, asSize(order.remaining));
    cell(row, order.status);
    const actions = row.insertCell();
    if (order.status === "open") {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Cancel";
      button.setAttribute("aria-label", `Cancel order ${order.id}`);
      button.dataset.id = order.id;
      actions.append(button);
    }
  });
  renderRows("trades", trades, 4, "No fills yet", (row, trade) => {
    cell(row, trade.side.toUpperCase(), trade.side);
    cell(row, asPrice(trade.price));
    cell(row, asSize(trade.size));
    cell(row, time.format(trade.created_at * 1000));
  });
  renderRows("exit-plans", exits, 6, "No exit plans yet", (row, plan) => {
    cell(row, asSize(plan.size));
    cell(row, asSize(plan.remaining));
    cell(row, asPrice(plan.stop));
    cell(row, asPrice(plan.target));
    const trigger = triggerLabels[plan.trigger];
    cell(row, trigger ? `${trigger} · ${plan.status}` : plan.status);
    const actions = row.insertCell();
    if (["armed", "triggered"].includes(plan.status)) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Cancel";
      button.setAttribute("aria-label", `Cancel exit plan ${plan.id}`);
      button.dataset.id = plan.id;
      actions.append(button);
    }
  });
  chart.update(orders, trades, exits);
  renderForm();
}

async function refresh() {
  if (loading || writing) return;
  loading = true;
  const request = ++latestRequest;
  try {
    const result = await api();
    if (request !== latestRequest) return;
    snapshot = result;
    render(result);
  } catch (error) {
    if (request !== latestRequest) return;
    snapshot = null;
    $("feed").dataset.live = "false";
    $("feed").textContent = "Connection unavailable";
    $("bid").textContent = $("ask").textContent = "—";
    renderForm();
  } finally {
    loading = false;
  }
}

async function changeOrder(operation, successMessage, target = "trade-notice") {
  if (writing) return;
  writing = true;
  latestRequest++;
  notice("", false, target);
  renderForm();
  try {
    const result = await operation();
    notice(successMessage(result), false, target);
  } catch (error) {
    notice(error instanceof ApiError ? error.message : "Connection unavailable. Check your orders.", true, target);
  } finally {
    writing = false;
    renderForm();
    await refresh();
  }
}

form.addEventListener("input", renderForm);
$("best-price").addEventListener("click", () => {
  if (!snapshot?.market) return;
  const levels = snapshot.book[side() === "buy" ? "sell" : "buy"];
  const quote = side() === "buy" ? snapshot.market.ask : snapshot.market.bid;
  price.value = asPrice(levels[0]?.price ?? quote);
  renderForm();
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!snapshot?.market) return;
  const order = { side: side(), kind: kind(), size: size.value };
  if (order.kind === "limit") order.price = price.value;
  changeOrder(
    () => api("/orders", "POST", order),
    (result) => {
      if (result.status === "filled") return "Order filled.";
      if (result.kind === "market") return "Partially filled. The remainder was cancelled.";
      return "Order added to the book.";
    },
  );
});
$("orders").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-id]");
  if (button) {
    button.disabled = true;
    changeOrder(() => api(`/orders/${button.dataset.id}`, "DELETE"), () => "Order cancelled.")
      .finally(() => { button.disabled = false; });
  }
});

exitForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!snapshot?.market || writing) return;
  const plan = Object.fromEntries(new FormData(exitForm));
  changeOrder(() => api("/exits", "POST", plan), () => {
    exitForm.reset();
    return "Exit plan armed. SOL reserved.";
  }, "exit-notice");
});
$("exit-plans").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-id]");
  if (button && !writing) {
    changeOrder(
      () => api(`/exits/${button.dataset.id}`, "DELETE"),
      () => "Exit plan cancelled. Remaining SOL released.",
      "exit-notice",
    );
  }
});

async function start() {
  try {
    if (!await prepareSession()) return;
    document.querySelector(".terminal").hidden = false;
    refresh();
    chart.start();
    setInterval(refresh, 2000);
  } catch (error) {
    const status = $("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
  }
}

start();
