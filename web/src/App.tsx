import { useEffect, useState } from "react";

import Footer from "./components/Footer.tsx";
import Link from "./components/Link.tsx";
import Nav from "./components/Nav.tsx";
import { getHealth } from "./lib/api.ts";
import { match, useRoute, useScrollReset } from "./lib/router.ts";
import type { Health } from "./lib/types.ts";
import MapPage from "./pages/MapPage.tsx";
import NotFound from "./pages/NotFound.tsx";
import ProvenancePage from "./pages/ProvenancePage.tsx";

/** Shown only when this deployment is not serving everything it should.
 *
 *  It used to open with "Phase 0 scaffold", which was true when it was written
 *  and had stopped being true long before anybody noticed — a banner that
 *  describes the project rather than the deployment goes stale silently and
 *  tells a reader nothing about what they are looking at. What follows is a
 *  statement about this instance, which the health check and the environment
 *  can both answer.
 */
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
      <span className="font-semibold">Not everything is running. </span>
      {messages.join(" ")}
    </div>
  );
}

/** Which page a path renders.
 *
 *  Order matters only in that the first match wins, and the patterns are
 *  exact, so there is nothing here that a reordering would change. A page is
 *  added by adding a row here and an entry in `Nav`'s PAGES, together, so the
 *  nav never points at a route that does not exist.
 */
function routeTo(path: string) {
  if (match("/", path)) return <MapPage />;
  if (match("/provenance", path)) return <ProvenancePage />;
  return <NotFound path={path} />;
}

/** Whether a route wants the whole viewport or ordinary page scroll.
 *
 *  The map is the exception: it fills what is left and manages its own
 *  overflow, because a map with the page scrollbar next to it scrolls the
 *  document when the reader means to pan.
 */
function isFullBleed(path: string): boolean {
  return match("/", path) !== null;
}

export default function App() {
  const path = useRoute();
  const [health, setHealth] = useState<Health | null>(null);

  useScrollReset(path);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    return () => controller.abort();
  }, []);

  const full = isFullBleed(path);

  return (
    <div className="flex h-full flex-col">
      {/* First in the tab order and invisible until focused, which is the one
          way a keyboard reader gets past a nav on every single page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50
                   focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm
                   focus:shadow focus:outline-2 focus:outline-sky-700"
      >
        Skip to content
      </a>

      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-slate-200 px-5 py-3">
        <Link
          to="/"
          className="text-base font-semibold text-slate-900 focus-visible:outline-2
                     focus-visible:outline-offset-2 focus-visible:outline-sky-700"
        >
          ClearSkies
        </Link>
        <p className="text-sm text-slate-500">Cumulative environmental burden in Louisiana</p>
        <div className="ml-auto">
          <Nav path={path} />
        </div>
      </header>

      <Banner health={health} />

      <main
        id="main"
        // The map fills the viewport; every other page scrolls normally and is
        // held to a readable measure.
        className={
          full
            ? "relative flex min-h-0 flex-1 flex-col"
            : "flex-1 overflow-y-auto px-5 py-8"
        }
      >
        {full ? routeTo(path) : <div className="mx-auto max-w-3xl">{routeTo(path)}</div>}
      </main>

      <Footer />
    </div>
  );
}
