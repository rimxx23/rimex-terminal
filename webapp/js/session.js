export function loginPage(next = location.pathname + location.search) {
  location.replace(`/login?${new URLSearchParams({ next })}`);
}

export async function webRequest(path, method = "GET", body) {
  const headers = { "X-Rimex-Request": "1" };
  if (body) headers["Content-Type"] = "application/json";
  return fetch(path, {
    method, headers, cache: "no-store",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function prepareSession() {
  const response = await webRequest("/api/auth/me");
  if (response.status === 401) {
    loginPage();
    return false;
  }
  if (!response.ok) throw new Error("Could not check your session. Try refreshing the page.");

  const { username } = await response.json();
  const controls = document.querySelector("[data-account]");
  const logout = controls.querySelector("button");
  controls.querySelector("[data-username]").textContent = username;
  controls.hidden = false;
  logout.addEventListener("click", async () => {
    logout.disabled = true;
    try {
      const result = await webRequest("/api/auth/logout", "POST");
      if (!result.ok) throw new Error();
      location.replace("/login");
    } catch {
      controls.querySelector("[role=status]").textContent = "Could not sign out. Try again.";
      logout.disabled = false;
    }
  });
  return { username };
}
