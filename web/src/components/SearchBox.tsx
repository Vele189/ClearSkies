import { useEffect, useId, useRef, useState } from "react";

import { searchPlaces } from "../lib/geocode.ts";
import type { Place } from "../lib/geocode.ts";

interface Props {
  onPick: (place: Place) => void;
}

export default function SearchBox({ onPick }: Props) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Clearing on the way in rather than from inside the effect: the effect only
  // ever schedules work, so it never sets state during a render pass.
  function handleChange(value: string) {
    setQuery(value);
    if (value.trim().length < 3) {
      setResults([]);
      setActive(-1);
      setError(null);
      setPending(false);
    }
  }

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 3) return;

    const controller = new AbortController();
    // Debounced so that typing a parish name is one request and not nine.
    const timer = setTimeout(() => {
      setPending(true);
      searchPlaces(trimmed, controller.signal)
        .then((places) => {
          setResults(places);
          setActive(places.length > 0 ? 0 : -1);
          setError(places.length === 0 ? "No match for that place." : null);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setResults([]);
          setError(err instanceof Error ? err.message : "Search is unavailable.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setPending(false);
        });
    }, 300);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query]);

  function choose(place: Place) {
    onPick(place);
    setResults([]);
    setActive(-1);
    setQuery(place.name);
    inputRef.current?.blur();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setResults([]);
      setActive(-1);
      return;
    }
    if (results.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const place = results[active] ?? results[0];
      choose(place);
    }
  }

  const open = results.length > 0;

  return (
    <div className="pointer-events-auto absolute top-2 left-2 z-10 w-[min(20rem,calc(100vw-5rem))] sm:top-3 sm:left-3">
      <input
        ref={inputRef}
        type="search"
        role="combobox"
        aria-label="Search for a place"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${listId}-${String(active)}` : undefined}
        autoComplete="off"
        placeholder="Search a place, or paste 30.05, -90.55"
        value={query}
        onChange={(event) => {
          handleChange(event.target.value);
        }}
        onKeyDown={handleKeyDown}
        className="w-full rounded-md border border-slate-300 bg-white/95 px-3 py-2 text-sm text-slate-900 shadow-sm backdrop-blur-sm placeholder:text-slate-400 focus:border-slate-500 focus:ring-1 focus:ring-slate-500 focus:outline-none"
      />

      {(open || error || pending) && (
        <div className="mt-1 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
          {open ? (
            <ul id={listId} role="listbox" aria-label="Search results">
              {results.map((place, i) => (
                <li
                  key={place.id}
                  id={`${listId}-${String(i)}`}
                  role="option"
                  aria-selected={i === active}
                  // Mouse down rather than click: the input's blur would tear
                  // the list down before a click ever landed on it.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    choose(place);
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={`cursor-pointer px-3 py-2 text-sm ${
                    i === active ? "bg-slate-100" : ""
                  }`}
                >
                  <span className="text-slate-900">{place.name}</span>
                  {place.context && (
                    <span className="ml-1.5 text-xs text-slate-500">{place.context}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2 text-sm text-slate-500" role="status">
              {pending ? "Searching…" : error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
