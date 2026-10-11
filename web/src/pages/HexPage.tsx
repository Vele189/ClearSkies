import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";

import HexPanel from "../components/HexPanel.tsx";
import Link from "../components/Link.tsx";
import { Mono } from "../components/Prose.tsx";
import { Button } from "../components/ui/button.tsx";
import { Skeleton } from "../components/ui/skeleton.tsx";
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
      <header className="mb-6">
        <p className="text-xs font-semibold tracking-[0.06em] text-faint uppercase">
          One hexagon
        </p>
        {/* The index is the heading, because it is what identifies this page.
            The previous title was "One hexagon" on every hexagon, which gave
            a reader with twenty tabs open twenty identical ones. */}
        <h1 className="mt-1.5 text-2xl font-semibold sm:text-3xl">
          <Mono>{h3}</Mono>
        </h1>
      </header>

      {error !== null && (
        <div>
          <p role="status" className="text-sm text-body">
            {error}
          </p>
          <Button asChild variant="outline" className="mt-5">
            {/* The router's anchor, so the click navigates in place. */}
            <Link to="/">
              <ArrowLeft aria-hidden="true" />
              Back to the map
            </Link>
          </Button>
        </div>
      )}

      {error === null && hex === null && (
        <div>
          <p role="status" className="text-sm text-muted-foreground">
            Loading hexagon…
          </p>
          <div className="mt-5 space-y-3">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-3.5 w-full max-w-md" />
            <Skeleton className="h-3.5 w-2/3 max-w-sm" />
          </div>
        </div>
      )}

      {hex !== null && (
        // Bordered rather than bare: the panel was drawn as a rail beside a map
        // and keeps that shape here, which is also what makes it one component
        // in two places rather than two components that drift.
        <div className="overflow-hidden rounded-lg border border-border bg-card">
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
