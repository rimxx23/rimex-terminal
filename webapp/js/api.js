export class ApiError extends Error {}

export async function scanToken(address, initData, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData },
      body: JSON.stringify({ address }),
    });
  } catch {
    throw new ApiError("Network error. Try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(typeof data.detail === "string" ? data.detail : "Request failed");
  }
  return data;
}
