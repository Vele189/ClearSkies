import { useCallback, useEffect, useState } from "react";

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

  const handleSelect = useCallback((h3: string) => {
    setError(null);
    getHex(h3)
      .then((detail) => {
        setHex(detail);
      })
      .catch((err: unknown) => {
        setHex(null);
        setError(err instanceof ApiError ? err.message : "Could not load that hexagon.");
      });
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-baseline gap-3 border-b border-slate-200 px-5 py-3">
        <h1 className="text-base font-semibold text-slate-900">ClearSkies</h1>
        <p className="text-sm text-slate-500">
          Cumulative environmental burden in Louisiana
        </p>
      </header>

      <Banner health={health} />

      {/* Column on a phone and a row on a desktop: a 24rem panel beside a map
          on a 390px screen leaves a strip of map nobody can pan. */}
      <main className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="min-h-0 min-w-0 flex-1">
          <MapView onSelect={handleSelect} />
        </div>
        {(hex || error) && (
          <div className="max-h-[55%] shrink-0 overflow-y-auto md:max-h-none md:w-[24rem]">
            {hex ? (
              <HexPanel hex={hex} onClose={() => setHex(null)} />
            ) : (
              <aside className="h-full border-l border-slate-200 bg-white p-5">
                <p className="text-sm text-slate-700">{error}</p>
                <button
                  onClick={() => setError(null)}
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
