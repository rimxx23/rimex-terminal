export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function scanToken(address, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl("/api/web/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address }),
    });
  } catch {
    throw new ApiError("Network error. Try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(typeof data.detail === "string" ? data.detail : "Request failed", response.status);
  }
  return data;
}
