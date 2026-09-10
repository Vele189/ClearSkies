import type { HexDetail, Health } from "./types.ts";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Non-JSON error body; the status text is the best available message.
    }
    throw new ApiError(response.status, detail);
  }
  const data: unknown = await response.json();
  return data as T;
}

export const getHealth = (signal?: AbortSignal) => request<Health>("/health", signal);

export const getHex = (h3: string, signal?: AbortSignal) =>
  request<HexDetail>(`/hex/${h3}`, signal);
