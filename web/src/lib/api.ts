import type { DocumentType, DraftResponse, HexDetail, Health } from "./types.ts";

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

/**
 * Ask for a draft about one hexagon.
 *
 * A POST, matching the endpoint. That is not a formality: the first call for a
 * hexagon spends money at a third-party API, and a GET is something browsers,
 * proxies and link previewers issue on their own.
 *
 * Failures here are answers rather than faults, and the caller renders the
 * `detail` the API sent rather than inventing its own wording. The API writes
 * that sentence knowing which of six things went wrong; the frontend does not.
 */
export async function postDraft(
  h3: string,
  documentType: DocumentType,
  signal?: AbortSignal,
): Promise<DraftResponse> {
  const response = await fetch(`${BASE}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ h3, document_type: documentType }),
    signal,
  });

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
  return data as DraftResponse;
}
