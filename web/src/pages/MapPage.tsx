import { useCallback, useEffect, useRef, useState } from "react";

import HexPanel from "../components/HexPanel.tsx";
import MapView from "../components/MapView.tsx";
import { Mono } from "../components/Prose.tsx";
import { Button } from "../components/ui/button.tsx";
import { Skeleton } from "../components/ui/skeleton.tsx";
import { getHex } from "../lib/api.ts";
import { readerError } from "../lib/wording.ts";
import type { HexDetail } from "../lib/types.ts";

/** What the rail shows while a hexagon is on its way.
 *
 *  The skeleton is decorative and `aria-hidden`; the sentence above it is the
 *  live region, and it names the hexagon being fetched. A reader who clicks
 *  twice quickly needs to know which of the two they are waiting on.
 */
function RailLoading({ h3 }: { h3: string }) {
  return (
    <div className="p-5">
      <p role="status" className="text-sm text-muted-foreground">
        Loading this area… <Mono className="sr-only">{h3}</Mono>
      </p>
      <div className="mt-5 space-y-3">
        <Skeleton className="h-7 w-28" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-4/5" />
        <Skeleton className="mt-6 h-3.5 w-2/3" />
        <Skeleton className="h-3.5 w-full" />
      </div>
    </div>
  );
}

export default function MapPage() {
  const [hex, setHex] = useState<HexDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        setError(readerError(err, "this spot"));
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
    <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
      {/* Every page owns its own h1, and the map's is the map. Visually hidden
          because the header already names the site on screen, and a screen
          reader arriving at <main> otherwise finds no heading at all: the
          header's "ClearSkies" became a link to the map when routing landed,
          and a link is not a heading. */}
      {/* No state named: this heading is the map, and which states the map
          covers is the masthead's line, read from /health. A heading that
          named one state would go stale where nothing checks it. */}
      <h1 className="sr-only">Map of pollution burden in Louisiana</h1>

      <div className="min-h-0 min-w-0 flex-1">
        <MapView onSelect={handleSelect} />
      </div>

      {/* A fixed-width rail alongside the map on a desktop viewport; a sheet
          over the bottom half of it on a phone, where 24rem of the 20rem-wide
          screen would leave no map at all. */}
      {(hex || error || loading) && (
        <div
          data-scroll-contain
          className="h-[55%] w-full shrink-0 overflow-y-auto border-t border-border bg-card
                     md:h-auto md:w-[25rem] md:border-t-0 md:border-l md:shadow-[-1px_0_0_0_var(--color-border)]"
        >
          {hex ? (
            // Keyed on the hexagon so that everything under the panel starts
            // again for a new one. A draft written about the last hex must not
            // stay on screen under this one's heading.
            <HexPanel key={hex.h3} hex={hex} onClose={close} standalone />
          ) : (
            <aside className="h-full">
              {loading ? (
                <RailLoading h3={loading} />
              ) : (
                <div className="p-5">
                  <p role="status" className="text-sm text-body">
                    {error}
                  </p>
                  <Button variant="outline" size="sm" onClick={close} className="mt-4">
                    Close
                  </Button>
                </div>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
