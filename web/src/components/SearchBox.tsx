import { useId, useState } from "react";

import { getHex } from "../lib/api.ts";
import { geocode, insidePilotState, parseQuery } from "../lib/search.ts";

interface Props {
  /** Move the map to a point. `select` opens the panel for a resolved hexagon. */
  onGoTo: (lon: number, lat: number, zoom?: number) => void;
  onSelect: (h3: string) => void;
}

const PLACEHOLDER = "Town, 30.45 -91.15, or an H3 index";

/**
 * Jump to a place, a coordinate, or a hexagon.
 *
 * Every failure says which of the three it tried and why it did not work. A
 * search box that clears itself and does nothing is the least debuggable
 * control on a page, and a map is exactly where a person arrives with a
 * coordinate from somewhere else and no idea why it will not take.
 */
export default function SearchBox({ onGoTo, onSelect }: Props) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();

  async function run(event: React.FormEvent) {
    event.preventDefault();
    const query = parseQuery(text);

    if (!query) {
      setStatus("Type a place, a latitude and longitude, or an H3 index.");
      return;
    }

    setBusy(true);
    setStatus(null);
    try {
      if (query.kind === "coords") {
        onGoTo(query.lon, query.lat, 12);
        setStatus(
          insidePilotState(query.lat, query.lon)
            ? null
            : "That point is outside Louisiana, which is the only state scored.",
        );
        return;
      }

      if (query.kind === "h3") {
        // Through the API rather than a client-side H3 library: the response
        // carries the centroid and the panel content in one round trip.
        const detail = await getHex(query.h3);
        const [lon, lat] = detail.centroid;
        onGoTo(lon, lat, 13);
        onSelect(detail.h3);
        return;
      }

      if (!import.meta.env.VITE_GEOCODER_URL) {
        setStatus(
          "Place search is off in this deployment. A latitude and longitude, " +
            "or an H3 index, will still work.",
        );
        return;
      }

      const place = await geocode(query.text);
      if (!place) {
        setStatus(`Nothing in Louisiana matched "${query.text}".`);
        return;
      }
      onGoTo(place.lon, place.lat, 12);
      setStatus(place.label);
    } catch {
      setStatus(
        query.kind === "h3"
          ? "No hexagon with that index. Check it is a Louisiana res-8 cell."
          : "The search could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      // `void`: the handler is async and a form submit expects no return.
      onSubmit={(event) => void run(event)}
      className="pointer-events-auto absolute left-3 top-3 z-10 w-[min(22rem,calc(100%-1.5rem))]"
      role="search"
    >
      <label htmlFor={inputId} className="sr-only">
        Search for a place, coordinate, or hexagon
      </label>
      <div className="flex gap-1.5 rounded-lg border border-slate-200 bg-white/95 p-1.5 shadow-lg backdrop-blur">
        <input
          id={inputId}
          // type="search" so mobile keyboards offer a search key and assistive
          // technology announces the control for what it is.
          type="search"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={PLACEHOLDER}
          className="min-w-0 flex-1 rounded px-2 py-1.5 text-sm text-slate-900 outline-none placeholder:text-slate-400"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="submit"
          disabled={busy}
          className="shrink-0 rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "…" : "Go"}
        </button>
      </div>
      {status && (
        <p
          role="status"
          className="mt-1 rounded bg-white/95 px-2 py-1 text-xs text-slate-600 shadow backdrop-blur"
        >
          {status}
        </p>
      )}
    </form>
  );
}
