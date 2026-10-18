import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import Footer from "./components/Footer.tsx";
import Link from "./components/Link.tsx";
import Nav from "./components/Nav.tsx";
import { Alert, AlertDescription, AlertTitle } from "./components/ui/alert.tsx";
import { getHealth } from "./lib/api.ts";
import { match, useRoute, useScrollReset } from "./lib/router.ts";
import type { Health } from "./lib/types.ts";
import AboutPage from "./pages/AboutPage.tsx";
import HexPage from "./pages/HexPage.tsx";
import MapPage from "./pages/MapPage.tsx";
import MethodologyPage from "./pages/MethodologyPage.tsx";
import ModelCardPage from "./pages/ModelCardPage.tsx";
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

  // A full-bleed strip rather than an inset card: it is a statement about the
  // whole deployment, so it spans the whole width and squares off its corners
  // and side borders, keeping only the rule that separates it from the header.
  return (
    <Alert variant="warn" className="rounded-none border-x-0 border-t-0 px-5 py-2.5">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Not everything is running</AlertTitle>
      <AlertDescription>{messages.join(" ")}</AlertDescription>
    </Alert>
  );
}

/** What the masthead says this deployment covers.
 *
 *  Read from /health rather than written here, because coverage is whatever
 *  `scored_state` holds. A masthead still naming one state after a second had
 *  been loaded would be the most-read wrong sentence on the site, and nothing
 *  would have failed to say so.
 *
 *  Before health answers it says the neutral form. Naming a state on the
 *  strength of a default would be guessing about the one thing this line is
 *  for.
 */
function coverage(health: Health | null): string {
  const burden = "Cumulative environmental burden";
  const states = health?.scored_states ?? [];

  if (states.length === 0) return burden;
  if (states.length === 1) return `${burden} in ${states[0].name}`;
  if (states.length === 2) return `${burden} in ${states[0].name} and ${states[1].name}`;
  return `${burden} across ${String(states.length)} states`;
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

  // The non-map path to a hexagon (CS-401). Not in the navigation: it is
  // somewhere a search or a shared link arrives, not a section of the site.
  const hex = match("/hex/:h3", path);
  if (hex) return <HexPage key={hex.h3} h3={hex.h3} />;

  if (match("/methodology", path)) return <MethodologyPage />;
  if (match("/model-card", path)) return <ModelCardPage />;
  if (match("/about", path)) return <AboutPage />;
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
    <div className="flex h-full flex-col bg-background">
      {/* First in the tab order and invisible until focused, which is the one
          way a keyboard reader gets past a nav on every single page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50
                   focus:rounded-md focus:border focus:border-border-strong focus:bg-card
                   focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground
                   focus:shadow-lg"
      >
        Skip to content
      </a>

      <header className="border-b border-border bg-card">
        {/* items-end rather than baseline: the nav's active tab is marked with
            a rule along its own bottom edge, which only meets the header's
            border if the nav sits on it. */}
        <div className="flex flex-wrap items-end justify-between gap-x-8 px-4 sm:px-5">
          <div className="py-3">
            <Link
              to="/"
              className="text-[1.0625rem] leading-tight font-semibold tracking-tight text-foreground"
            >
              ClearSkies
            </Link>
            <p className="mt-0.5 text-xs leading-tight text-faint">{coverage(health)}</p>
          </div>
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
            : "flex-1 overflow-y-auto px-5 py-10 sm:py-12"
        }
      >
        {full ? routeTo(path) : <div className="mx-auto max-w-4xl">{routeTo(path)}</div>}
      </main>

      <Footer compact={full} />
    </div>
  );
}
