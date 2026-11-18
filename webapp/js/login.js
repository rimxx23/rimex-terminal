import { webRequest } from "./session.js";

const form = document.getElementById("auth-form");
const title = document.getElementById("auth-title");
const password = document.getElementById("password");
const hint = document.getElementById("password-hint");
const error = document.getElementById("auth-error");
const submit = document.getElementById("auth-submit");
const toggle = document.getElementById("auth-toggle");
let registering = false;

function destination() {
  const next = new URLSearchParams(location.search).get("next");
  if (!next) return "/";
  try {
    const target = new URL(next, location.origin);
    return target.origin === location.origin && ["/", "/scanner", "/trade", "/swap", "/portfolio", "/profile"].includes(target.pathname)
      ? target.pathname + target.search
      : "/";
  } catch {
    return "/";
  }
}

toggle.addEventListener("click", () => {
  registering = !registering;
  title.textContent = registering ? "Create your account" : "Sign in to Rimex";
  submit.textContent = registering ? "Create account" : "Sign in";
  toggle.textContent = registering ? "Back to sign in" : "Create an account";
  password.autocomplete = registering ? "new-password" : "current-password";
  password.setAttribute("aria-describedby", registering ? hint.id : "");
  hint.hidden = !registering;
  error.textContent = "";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  submit.disabled = toggle.disabled = true;
  try {
    const path = registering ? "/api/trade/register" : "/api/auth/login";
    const response = await webRequest(path, "POST", Object.fromEntries(new FormData(form)));
    if (response.ok) {
      location.replace(destination());
      return;
    }
    const { detail } = await response.json().catch(() => ({}));
    error.textContent = typeof detail === "string" ? detail : "Check your username and password.";
  } catch {
    error.textContent = "Connection unavailable. Try again.";
  } finally {
    submit.disabled = toggle.disabled = false;
  }
});
