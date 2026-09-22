import { useEffect, useState } from "react";

import HexPanel from "../components/HexPanel.tsx";
import Link from "../components/Link.tsx";
import { ApiError, getHex } from "../lib/api.ts";
import { navigate } from "../lib/router.ts";
import type { HexDetail } from "../lib/types.ts";

/** One hexagon, without the map (CS-401).
 *
 *  The accessibility requirement is a non-map path to the same data, and this
 *  is mostly routing rather than new work: `GET /hex/{h3}` already returns
 *  exactly the payload `HexPanel` renders, and the panel is already
 *  keyboard-navigable from AUD-10. What was missing was an address for it.
 *
 *  It is also the page a search result should land on and the thing a reader
 *  can send to somebody else, neither of which a click on a canvas can be.
 */
export default function HexPage({ h3 }: { h3: string }) {
  const [hex, setHex] = useState<HexDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // No reset on h3 here: App keys this component by the hexagon, so a
  // different one is a different component with its own state rather than this
  // one being emptied and refilled. That is also what stops the previous
  // hexagon's panel showing for a frame under the new one's heading.
  useEffect(() => {
    const controller = new AbortController();
    getHex(h3, controller.signal)
      .then((detail) => {
        if (controller.signal.aborted) return;
        setHex(detail);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Could not load that hexagon.");
      });
    return () => controller.abort();
  }, [h3]);

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold text-slate-900">One hexagon</h1>
      <p className="mb-4 text-sm text-slate-500">
        <span className="font-mono text-xs">{h3}</span>
      </p>

      {error !== null && (
        <div>
          <p role="status" className="text-sm text-slate-700">
            {error}
          </p>
          <p className="mt-4 text-sm">
            <Link
              to="/"
              className="text-sky-800 underline focus-visible:outline-2
                         focus-visible:outline-offset-2 focus-visible:outline-sky-700"
            >
              Back to the map
            </Link>
          </p>
        </div>
      )}

      {error === null && hex === null && (
        <p role="status" className="text-sm text-slate-500">
          Loading hexagon…
        </p>
      )}

      {hex !== null && (
        // Bordered rather than bare: the panel was drawn as a rail beside a map
        // and keeps that shape here, which is also what makes it one component
        // in two places rather than two components that drift.
        <div className="rounded border border-slate-200">
          <HexPanel
            key={hex.h3}
            hex={hex}
            // The panel's close button means "done with this hexagon". On the
            // map that returns to the map, and so does it here.
            onClose={() => {
              navigate("/");
            }}
          />
        </div>
      )}
    </div>
  );
}
