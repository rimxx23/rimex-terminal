const tg = window.Telegram?.WebApp;

export function initTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("#000000");
  tg.setBackgroundColor?.("#000000");
}

export const initData = () => tg?.initData ?? "";

export const telegramUser = () => tg?.initDataUnsafe?.user ?? null;

export const startParam = () => tg?.initDataUnsafe?.start_param ?? null;

export function haptic(type) {
  tg?.HapticFeedback?.notificationOccurred(type);
}

export function openLink(url) {
  if (initData() && tg?.openLink) tg.openLink(url);
  else window.open(url, "_blank", "noopener");
}

export function showBackButton(onBack) {
  if (!initData() || !tg?.BackButton) return () => {};
  tg.BackButton.onClick(onBack);
  tg.BackButton.show();
  return () => {
    tg.BackButton.offClick(onBack);
    tg.BackButton.hide();
  };
}

function cloudStorage() {
  const cloud = tg?.CloudStorage;
  if (!cloud || !tg.isVersionAtLeast?.("6.9")) return null;
  return {
    getItem: (key) =>
      new Promise((resolve) => cloud.getItem(key, (error, value) => resolve(error ? null : value))),
    setItem: (key, value) =>
      new Promise((resolve) => cloud.setItem(key, value, () => resolve())),
  };
}

function localStorageBackend() {
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

export function createStorage() {
  return (initData() ? cloudStorage() : null) ?? localStorageBackend();
}
