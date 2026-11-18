import { createBrowserStorage, createHistory } from "./history.js?v=8";
import { prepareSession } from "./session.js?v=8";
import { renderProfile } from "./views/profile.js?v=8";

const history = createHistory(createBrowserStorage());
const content = document.getElementById("profile-content");

async function start() {
  try {
    const user = await prepareSession();
    if (!user) return;

    async function show() {
      renderProfile(content, {
        user,
        entries: await history.load(),
        onSelect(address) {
          location.assign(`/scanner?${new URLSearchParams({ address })}`);
        },
        async onClear() {
          await history.clear();
          await show();
        },
      });
    }
    await show();
    document.querySelector(".profile-terminal").hidden = false;
  } catch (error) {
    const status = document.getElementById("web-auth-status");
    status.textContent = error.message;
    status.hidden = false;
  }
}

start();
