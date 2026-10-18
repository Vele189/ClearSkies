import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils.ts";

import { searchPlaces } from "../lib/geocode.ts";
import type { Place } from "../lib/geocode.ts";

interface Props {
  onPick: (place: Place) => void;
}

export default function SearchBox({ onPick }: Props) {
  const listId = useId();
  const [query, setQuery] = useState("");
  /** What the geocoder is asked for, which is not always what the input shows.
   *  Only typing sets it. Picking a result writes the place's name into the
   *  input, and if that were a search too the list would reopen under the
   *  reader straight after they had chosen from it. */
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Clearing on the way in rather than from inside the effect: the effect only
  // ever schedules work, so it never sets state during a render pass.
  function handleChange(value: string) {
    setQuery(value);
    setTerm(value);
    if (value.trim().length < 3) {
      setResults([]);
      setActive(-1);
      setError(null);
      setPending(false);
    }
  }

  useEffect(() => {
    const trimmed = term.trim();
    if (trimmed.length < 3) return;

    const controller = new AbortController();
    // Debounced so that typing a parish name is one request and not nine.
    const timer = setTimeout(() => {
      setPending(true);
      searchPlaces(trimmed, controller.signal)
        .then((places) => {
          setResults(places);
          setActive(places.length > 0 ? 0 : -1);
          setError(places.length === 0 ? "No place in Louisiana matches that." : null);
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
  }, [term]);

  /** Closes the list and cancels any search still pending, so a response that
   *  was already on its way cannot reopen it. Clearing the term is what
   *  cancels: the effect's cleanup aborts the request and the timer. */
  function dismiss() {
    setTerm("");
    setResults([]);
    setActive(-1);
    setError(null);
    setPending(false);
  }

  function choose(place: Place) {
    onPick(place);
    dismiss();
    setQuery(place.name);
    inputRef.current?.blur();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      dismiss();
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
    <div className="pointer-events-auto absolute top-2 left-2 z-10 w-[min(22rem,calc(100vw-5rem))] sm:top-3 sm:left-3">
      <div className="relative">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint"
        />
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-label="Search for a town or address in Louisiana"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && active >= 0 ? `${listId}-${String(active)}` : undefined}
          autoComplete="off"
          placeholder="Search a town or address in Louisiana"
          value={query}
          onChange={(event) => {
            handleChange(event.target.value);
          }}
          onKeyDown={handleKeyDown}
          className="h-10 w-full rounded-lg border border-input bg-card/95 pr-3 pl-9 text-sm
                     text-foreground shadow-md ring-1 ring-black/5 backdrop-blur-sm
                     placeholder:text-faint
                     [&::-webkit-search-cancel-button]:cursor-pointer"
        />
      </div>

      {(open || error || pending) && (
        <div className="mt-1.5 overflow-hidden rounded-lg border border-border bg-card shadow-lg ring-1 ring-black/5">
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
                  className={cn(
                    "cursor-pointer px-3 py-2 text-sm",
                    i === active && "bg-accent",
                  )}
                >
                  <span className="font-medium text-foreground">{place.name}</span>
                  {place.context && (
                    <span className="ml-1.5 text-xs text-muted-foreground">{place.context}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2 text-sm text-muted-foreground" role="status">
              {pending ? "Searching…" : error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
