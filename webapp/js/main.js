import { ApiError, scanToken } from "./api.js";
import { fillMissingData } from "./fallback.js";
import { createHistory } from "./history.js";
import { SOLANA_ADDRESS_RE } from "./levels.js";
import {
  createStorage,
  haptic,
  initData,
  initTelegram,
  openLink,
  showBackButton,
  startParam,
  telegramUser,
} from "./telegram.js";
import { renderAvatar, renderProfile } from "./views/profile.js";
import { renderHint, renderLoading, renderMessage, renderReport } from "./views/scan.js";

const HAPTIC_BY_VERDICT = { danger: "warning", warning: "warning", safe: "success", unknown: "warning" };

const dom = {
  form: document.getElementById("scan-form"),
  input: document.getElementById("address"),
  button: document.getElementById("scan-button"),
  result: document.getElementById("result"),
  template: document.getElementById("report-template"),
  scanView: document.getElementById("scan-view"),
  profileView: document.getElementById("profile-view"),
  profileContent: document.getElementById("profile-content"),
  profileButton: document.getElementById("profile-button"),
  backButton: document.getElementById("back-button"),
  toast: document.getElementById("toast"),
};

const history = createHistory(createStorage());
const user = telegramUser();
let hideBackButton = () => {};
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

function showScanView() {
  hideBackButton();
  hideBackButton = () => {};
  dom.profileView.hidden = true;
  dom.scanView.hidden = false;
}

async function showProfileView() {
  dom.scanView.hidden = true;
  dom.profileView.hidden = false;
  hideBackButton = showBackButton(showScanView);
  await refreshProfile();
}

async function refreshProfile() {
  renderProfile(dom.profileContent, {
    user,
    entries: await history.load(),
    onSelect: (address) => {
      showScanView();
      dom.input.value = address;
      scan(address);
    },
    onClear: async () => {
      await history.clear();
      await refreshProfile();
    },
  });
}

async function scan(address) {
  dom.button.disabled = true;
  renderLoading(dom.result);
  try {
    const report = await fillMissingData(await scanToken(address, initData()));
    const verdict = renderReport(dom.result, dom.template, report, { onOpenLink: openLink, onCopy: copyAddress });
    haptic(HAPTIC_BY_VERDICT[verdict.level]);
    await history.add({ address, symbol: report.symbol, verdict: verdict.level, scannedAt: Date.now() });
  } catch (error) {
    renderMessage(dom.result, error instanceof ApiError ? error.message : "Something went wrong. Try again.");
    haptic("error");
  } finally {
    dom.button.disabled = false;
  }
}

function start() {
  initTelegram();
  dom.profileButton.replaceChildren(renderAvatar(user, "avatar"));
  dom.profileButton.addEventListener("click", showProfileView);
  dom.backButton.addEventListener("click", showScanView);

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
  const initial = startParam() || new URLSearchParams(location.search).get("address");
  if (initial && SOLANA_ADDRESS_RE.test(initial)) {
    dom.input.value = initial;
    scan(initial);
  }
}

start();
