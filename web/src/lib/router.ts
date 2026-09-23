/** A router, because five pages did not justify a routing library.
 *
 *  What the app needs is a current path, a way to change it without a reload,
 *  and one dynamic segment for `/hex/:h3`. React Router brings loaders, nested
 *  outlets, data APIs and a bundle to match, none of which apply here, and the
 *  map is already the largest thing a first view pulls (CS-408). This is the
 *  same trade `pipeline/tiles/build.py` made against tippecanoe: the reference
 *  library is better at the general problem and this is not the general
 *  problem.
 *
 *  History routing rather than hashes, because the API and the docs are linked
 *  by path and a `#` in front of them would read as a different kind of thing.
 *  The frontend service serves `dist` with `serve -s`, whose SPA fallback
 *  answers every path with `index.html`, so a deep link works on a cold load.
 */

import { useCallback, useEffect, useSyncExternalStore } from "react";

/** Fired on `navigate`, because `pushState` does not emit `popstate`. */
const CHANGED = "clearskies:navigate";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

function currentPath(): string {
  return window.location.pathname;
}

/** The path being rendered. Re-renders the caller when it changes. */
export function useRoute(): string {
  // useSyncExternalStore rather than useState plus an effect: the path is
  // external mutable state, and this is the hook that exists for reading one
  // without tearing under concurrent rendering.
  return useSyncExternalStore(subscribe, currentPath, () => "/");
}

/** Change the path without reloading. */
export function navigate(to: string, { replace = false } = {}): void {
  if (to === currentPath()) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(CHANGED));
}

/** True when `path` is `pattern`, filling `:params`. Null when it is not.
 *
 *  Exact matches only. There is no nesting here and a prefix match would make
 *  `/` match everything.
 */
export function match(pattern: string, path: string): Record<string, string> | null {
  const expected = pattern.split("/").filter(Boolean);
  const actual = path.split("/").filter(Boolean);
  if (expected.length !== actual.length) return null;

  const params: Record<string, string> = {};
  for (const [index, segment] of expected.entries()) {
    const found = actual[index];
    if (segment.startsWith(":")) {
      // An empty segment is not a value. `/hex/` must not match `/hex/:h3`
      // with an h3 of "", which would send the API a request for nothing.
      if (!found) return null;
      params[segment.slice(1)] = decodeURIComponent(found);
      continue;
    }
    if (segment !== found) return null;
  }
  return params;
}

/** Whether a click should be left to the browser rather than routed.
 *
 *  A modified click is the reader asking for a new tab or a download, and
 *  swallowing it is the thing that makes a hand-rolled router annoying to use.
 */
function isPlainClick(event: React.MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    !event.defaultPrevented &&
    // An explicit target is also the reader asking for somewhere else.
    (!event.currentTarget.target || event.currentTarget.target === "_self")
  );
}

export function useNavigate(): (to: string) => void {
  return useCallback((to: string) => navigate(to), []);
}

/** Restores the top of the page on a route change.
 *
 *  A reader who follows a nav link from halfway down the methodology page and
 *  lands halfway down the provenance page will reasonably think the link was
 *  broken.
 */
export function useScrollReset(path: string): void {
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [path]);
}

export { CHANGED as NAVIGATION_EVENT, isPlainClick };
