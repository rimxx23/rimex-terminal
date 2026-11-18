import { ApiError, scanToken } from "./api.js?v=2";
import { loginPage, prepareSession } from "./session.js?v=2";
import { fillMissingData } from "./fallback.js";
import { createBrowserStorage, createHistory } from "./history.js?v=2";
import { SOLANA_ADDRESS_RE } from "./levels.js";
import { renderAvatar, renderProfile } from "./views/profile.js?v=2";
import { renderHint, renderLoading, renderMessage, renderReport } from "./views/scan.js?v=6";

const dom = {
  form: document.getElementById("scan-form"),
  input: document.getElementById("address"),
  button: document.getElementById("scan-button"),
  result: document.getElementById("result"),
  template: document.getElementById("report-template"),
  scanView: document.getElementById("scan-view"),
  toast: document.getElementById("toast"),
};

const history = createHistory(createBrowserStorage());
let toastTimer;

function showToast(text) {
  dom.toast.textContent = text;
  dom.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => dom.toast.classList.remove("visible"), 1500);
}

async function copyAddress(address) {
  try {
    await navigator.clipboard.writeText(address);
    showToast("Address copied");
  } catch {
    showToast("Copy not available");
  }
}

async function scan(address) {
  dom.button.disabled = true;
  renderLoading(dom.result);
  try {
    const report = await fillMissingData(await scanToken(address));
    const verdict = renderReport(dom.result, dom.template, report, {
      onOpenLink: (url) => window.open(url, "_blank", "noopener"), onCopy: copyAddress,
    });
    await history.add({ address, symbol: report.symbol, verdict: verdict.level, scannedAt: Date.now() });
  } catch (error) {
    if (error.status === 401) {
      loginPage();
      return;
    }
    renderMessage(dom.result, error instanceof ApiError ? error.message : "Something went wrong. Try again.");
  } finally {
    dom.button.disabled = false;
  }
}

async function start() {
  try {
    if (!await prepareSession()) return;
  } catch (error) {
    const status = document.getElementById("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
    return;
  }
  dom.scanView.hidden = false;

  dom.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const address = dom.input.value.trim();
    if (!address) return;
    if (!SOLANA_ADDRESS_RE.test(address)) {
      renderMessage(dom.result, "This doesn't look like a Solana token address.");
      return;
    }
    dom.input.blur();
    scan(address);
  });

  renderHint(dom.result);
  const initial = new URLSearchParams(location.search).get("address");
  if (initial && SOLANA_ADDRESS_RE.test(initial)) {
    dom.input.value = initial;
    scan(initial);
  }
}

start();
