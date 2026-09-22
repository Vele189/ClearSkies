import { useCallback, useEffect, useRef, useState } from "react";

import HexPanel from "./components/HexPanel.tsx";
import MapView from "./components/MapView.tsx";
import { ApiError, getHealth, getHex } from "./lib/api.ts";
import type { HexDetail, Health } from "./lib/types.ts";

function Banner({ health }: { health: Health | null }) {
  const tilesConfigured = Boolean(import.meta.env.VITE_TILES_URL);
  if (health?.status === "ok" && tilesConfigured) return null;

  const messages: string[] = [];
  if (!tilesConfigured) {
    messages.push("No tile archive configured, so the map shows the basemap only.");
  }
  if (health === null) {
    messages.push("The API is not reachable.");
  } else {
    messages.push(...health.notes);
  }

  return (
    <div className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-900">
      <span className="font-semibold">Phase 0 scaffold. </span>
      {messages.join(" ")}
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [hex, setHex] = useState<HexDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    return () => controller.abort();
  }, []);

  /** The hexagon being fetched, while a fetch is in flight. Shown in the rail
   *  in place of whichever hex was open before, which is no longer the one the
   *  reader asked about. */
  const [loading, setLoading] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);

  // Each selection aborts the one before it. Without that, two clicks in quick
  // succession race, and whichever response lands last is the panel the reader
  // sees, which need not be the hex they clicked last.
  const handleSelect = useCallback((h3: string) => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;

    setError(null);
    setHex(null);
    setLoading(h3);
    getHex(h3, controller.signal)
      .then((detail) => {
        if (controller.signal.aborted) return;
        setHex(detail);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Could not load that hexagon.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        pending.current = null;
        setLoading(null);
      });
  }, []);

  const close = useCallback(() => {
    pending.current?.abort();
    pending.current = null;
    setLoading(null);
    setHex(null);
    setError(null);
  }, []);

  useEffect(() => () => pending.current?.abort(), []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-baseline gap-3 border-b border-slate-200 px-5 py-3">
        <h1 className="text-base font-semibold text-slate-900">ClearSkies</h1>
        <p className="text-sm text-slate-500">
          Cumulative environmental burden in Louisiana
        </p>
      </header>

      <Banner health={health} />

      <main className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="min-h-0 min-w-0 flex-1">
          <MapView onSelect={handleSelect} />
        </div>
        {/* A fixed-width rail alongside the map on a desktop viewport; a sheet
            over the bottom half of it on a phone, where 24rem of the 20rem-wide
            screen would leave no map at all. */}
        {(hex || error || loading) && (
          <div className="h-[55%] w-full shrink-0 border-t border-slate-200 md:h-auto md:w-[24rem] md:border-t-0">
            {hex ? (
              // Keyed on the hexagon so that everything under the panel starts
              // again for a new one. A draft written about the last hex must not
              // stay on screen under this one's heading.
              <HexPanel key={hex.h3} hex={hex} onClose={close} />
            ) : (
              <aside className="h-full bg-white p-5 md:border-l md:border-slate-200">
                {loading ? (
                  <p role="status" className="text-sm text-slate-500">
                    Loading hexagon <span className="font-mono text-xs">{loading}</span>…
                  </p>
                ) : (
                  <p className="text-sm text-slate-700">{error}</p>
                )}
                <button
                  onClick={close}
                  className="mt-3 rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
                >
                  Close
                </button>
              </aside>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
