import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHex } from "./api.ts";

function mockFetch(status: number, body: unknown, ok = status < 400) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: "Error",
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getHex", () => {
  it("surfaces the API's explanation rather than a generic message", async () => {
    // The API explains why a cell has no score. Losing that in the client
    // would turn 'the pipeline has not run' into 'something went wrong'.
    mockFetch(503, {
      detail: "No scored data yet. The Phase 1 ingestion and Phase 2 scoring steps have not run.",
    });

    await expect(getHex("88444600ddfffff")).rejects.toThrowError(
      /Phase 1 ingestion and Phase 2 scoring steps have not run/,
    );
  });

  it("carries the status code so callers can distinguish 404 from 503", async () => {
    mockFetch(404, { detail: "No scored hex in the pilot state." });

    const error = await getHex("88444600ddfffff").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
  });

  it("falls back to status text when the error body is not JSON", async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new Error("not json")),
    });
    vi.stubGlobal("fetch", spy);

    await expect(getHex("88444600ddfffff")).rejects.toThrowError(/Bad Gateway/);
  });
});
