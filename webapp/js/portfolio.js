import { loginPage, prepareSession, webRequest } from "./session.js";

const $ = (id) => document.getElementById(id);
const pageSize = 25;
const time = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const amount = new Intl.NumberFormat(undefined, { maximumFractionDigits: 5 });
const currency = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const profit = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 5, signDisplay: "exceptZero" });
let page = 0;
let loading = false;

function money(value, formatted = currency) {
  return value === null ? "—" : `${formatted.format(Number(value))} USDT`;
}

function cell(row, value) {
  row.insertCell().textContent = value;
}

function render(data) {
  $("portfolio-equity").textContent = money(data.equity);
  $("portfolio-realized").textContent = money(data.realized_pnl, profit);
  $("portfolio-unrealized").textContent = money(data.unrealized_pnl, profit);
  $("portfolio-average").textContent = money(data.average_price, amount);
  $("portfolio-sol").textContent = amount.format(Number(data.balances.SOL));
  $("portfolio-usdt").textContent = amount.format(Number(data.balances.USDT));
  $("portfolio-mark").textContent = money(data.mark_price, amount);
  $("portfolio-feed").dataset.live = String(data.mark_price !== null);
  $("portfolio-feed").textContent = data.mark_price === null ? "Waiting for market quote" : "Binance mark price";
  const basis = $("portfolio-basis");
  const startingPrice = money(data.starting_sol_price, amount);
  basis.hidden = !data.starting_price_source;
  basis.textContent = data.starting_price_source === "first_operation"
    ? `Starting SOL valued at your first recorded execution price · ${startingPrice} per SOL`
    : `Starting SOL valued at your first portfolio quote · ${startingPrice} per SOL`;

  if (data.starting_price_source && !data.accounting_ready) {
    basis.textContent = "Earlier activity could not be reconciled. P&L is unavailable.";
  }

  const rows = data.journal.map((operation) => {
    const row = document.createElement("tr");
    cell(row, time.format(operation.happened_at * 1000));
    cell(row, { stop_loss: "Stop loss", take_profit: "Take profit" }[operation.trigger] ?? (operation.source === "swap" ? "Jupiter Swap" : "Order book"));
    cell(row, operation.side.toUpperCase());
    cell(row, amount.format(Number(operation.sol)));
    cell(row, amount.format(Number(operation.usdt)));
    cell(row, amount.format(Number(operation.price)));
    cell(row, money(operation.realized_pnl, profit));
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr");
    cell(row, "No operations yet");
    row.cells[0].colSpan = 7;
    row.cells[0].className = "table-empty";
    rows.push(row);
  }
  $("journal").replaceChildren(...rows);
  const total = data.total_operations;
  $("journal-count").textContent = total ? `${page * pageSize + 1}–${page * pageSize + data.journal.length} of ${total}` : "";
  $("journal-page").hidden = total <= pageSize;
  $("journal-prev").disabled = page === 0;
  $("journal-next").disabled = (page + 1) * pageSize >= total;
}

async function refresh(nextPage = page) {
  if (loading || document.hidden) return;
  loading = true;
  const status = $("web-auth-status");
  try {
    const response = await webRequest(`/api/portfolio?limit=${pageSize}&offset=${nextPage * pageSize}`);
    if (response.status === 401) {
      loginPage();
      return;
    }
    if (!response.ok) throw new Error("Portfolio is temporarily unavailable.");
    const data = await response.json();
    page = nextPage;
    render(data);
    status.hidden = true;
  } catch {
    status.textContent = "Could not refresh the portfolio. Retrying…";
    status.hidden = false;
  } finally {
    loading = false;
  }
}

$("journal-prev").addEventListener("click", () => refresh(page - 1));
$("journal-next").addEventListener("click", () => refresh(page + 1));

async function start() {
  try {
    if (!await prepareSession()) return;
    document.querySelector(".portfolio-terminal").hidden = false;
    refresh();
    setInterval(refresh, 4000);
  } catch (error) {
    const status = $("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
  }
}

start();
