import { loginPage, prepareSession, webRequest } from "./session.js?v=8";

const $ = (id) => document.getElementById(id);
const amount = new Intl.NumberFormat(undefined, { maximumFractionDigits: 5 });
const money = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const profit = new Intl.NumberFormat(undefined, { maximumFractionDigits: 5, signDisplay: "exceptZero" });
let loading = false;

function value(number, format) {
  return number === null ? "—" : `${format.format(Number(number))} USDT`;
}

function row(item) {
  const entry = document.createElement("li");
  const summary = document.createElement("span");
  const title = document.createElement("strong");
  const source = document.createElement("small");
  const total = document.createElement("span");
  title.textContent = `${item.side === "buy" ? "Bought" : "Sold"} ${amount.format(Number(item.sol))} SOL`;
  source.textContent = { stop_loss: "Stop loss", take_profit: "Take profit" }[item.trigger] ?? (item.source === "swap" ? "Jupiter Swap" : "Order book");
  total.textContent = value(item.usdt, amount);
  total.className = "overview-total";
  summary.append(title, source);
  entry.append(summary, total);
  return entry;
}

async function refresh() {
  if (loading || document.hidden) return;
  loading = true;
  const status = $("overview-status");
  try {
    const response = await webRequest("/api/portfolio?limit=5");
    if (response.status === 401) {
      loginPage();
      return;
    }
    if (!response.ok) throw new Error();
    const data = await response.json();
    $("overview-equity").textContent = value(data.equity, money);
    $("overview-pnl").textContent = value(data.realized_pnl, profit);
    $("overview-mark").textContent = value(data.mark_price, amount);
    const items = data.journal.map(row);
    if (!items.length) {
      const empty = document.createElement("li");
      empty.className = "overview-empty";
      empty.textContent = "No trades or swaps yet";
      items.push(empty);
    }
    $("overview-journal").replaceChildren(...items);
    status.hidden = true;
  } catch {
    status.textContent = "Market and account data are temporarily unavailable.";
    status.hidden = false;
  } finally {
    loading = false;
  }
}

async function start() {
  try {
    const user = await prepareSession();
    if (!user) return;
    $("overview-user").textContent = user.username;
    document.querySelector(".overview-terminal").hidden = false;
    refresh();
    setInterval(refresh, 5000);
  } catch (error) {
    const status = $("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
  }
}

start();
