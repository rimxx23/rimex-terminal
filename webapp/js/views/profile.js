import { el } from "../dom.js";
import { humanAge, initials, shortAddress } from "../format.js";
import { VERDICT_TITLES } from "../levels.js";

const TELEGRAM_PHOTO_RE = /^https:\/\/t\.me\//;

export function renderAvatar(user, className = "avatar") {
  if (user?.photo_url && TELEGRAM_PHOTO_RE.test(user.photo_url)) {
    return el("img", {
      className,
      attrs: { src: user.photo_url, alt: "", referrerpolicy: "no-referrer" },
    });
  }
  return el("span", { className, text: initials(user) });
}

function renderUser(user) {
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") : "Guest";
  return el("div", { className: "profile-user" }, [
    renderAvatar(user, "avatar avatar-large"),
    el("div", {}, [
      el("div", { className: "profile-name", text: name }),
      el("div", { className: "profile-handle", text: user?.username ? `@${user.username}` : "Open from Telegram to sync history" }),
    ]),
  ]);
}

function renderEntry(entry, onSelect, now) {
  return el("button", { className: "history-item", attrs: { type: "button" }, onClick: () => onSelect(entry.address) }, [
    el("div", { className: "history-main" }, [
      el("span", { className: "history-symbol", text: entry.symbol || shortAddress(entry.address) }),
      el("span", { className: "history-address", text: shortAddress(entry.address) }),
    ]),
    el("div", { className: "history-meta" }, [
      el("span", { className: `history-verdict ${entry.verdict}`, text: VERDICT_TITLES[entry.verdict] }),
      el("span", { className: "history-time", text: entry.scannedAt ? `${humanAge(entry.scannedAt, now)} ago` : "" }),
    ]),
  ]);
}

export function renderProfile(container, { user, entries, onSelect, onClear, now = Date.now() }) {
  const list = entries.length
    ? el("div", { className: "history" }, entries.map((entry) => renderEntry(entry, onSelect, now)))
    : el("div", { className: "hint", text: "No scans yet. Scanned tokens will appear here." });

  const children = [
    renderUser(user),
    el("div", { className: "section-title" }, [
      el("span", { text: `Recent scans · ${entries.length}/10` }),
      entries.length
        ? el("button", { className: "link-button", text: "Clear", attrs: { type: "button" }, onClick: onClear })
        : "",
    ]),
    list,
  ];
  container.replaceChildren(...children);
}
