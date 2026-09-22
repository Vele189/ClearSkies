// Railway infrastructure as code.
//
// STATUS: checked against the railway SDK (npm `railway`, v3.11.0) type
// definitions on 2026-09-11. It typechecks, and every field below exists in
// that schema. It has NOT yet been applied to a live Railway project: the
// two services still have to be created and a deploy confirmed before
// `railway config pull` can regenerate this file from reality.
//
// Two services, `web` and `api`. The database is not one of them: it is a Neon
// branch, which provides PostGIS, h3 and pgvector as managed extensions, so
// there is no image to build and no volume to look after here. The api reaches
// it through DATABASE_URL, sealed in the dashboard. infra/postgres still builds
// the equivalent database as a container, for offline work and for CI, and
// nothing in this file deploys it.
//
// Two things must be done in the dashboard or the CLI, because they are not
// expressible in the IaC schema at all:
//
//   1. Public domains. RAILWAY_PUBLIC_DOMAIN is only populated once a domain
//      is applied, and the generated hostname is assigned by Railway, so it
//      cannot be written here ahead of time. Run `railway domain` against
//      `web` and `api`.
//   2. CDN caching. It is off by default and toggled per service under
//      Settings > Edge, or with `railway cdn enable`. Enable it on `web`
//      only. Never on `api`: the drafting endpoint is a POST returning a
//      document generated per hex, so an edge cache in front of it buys
//      nothing and risks serving one request's output to another. Railway's
//      own 2026-03-30 incident was exactly that failure mode.
//
// Both of those need CLI >= 5.x. `railway config` and `railway cdn` do not
// exist in 4.31.0.
//
//   3. Per-pull-request preview environments. Railway builds these from
//      additional environments, which the Hobby plan this project runs on does
//      not include; they need a Pro workspace. **Previews are therefore not
//      available and reviewers check a branch locally**, which is what
//      `make web` is for. This is recorded rather than left to be rediscovered:
//      a reviewer looking for a preview URL that was never going to exist will
//      assume the deploy is broken.
//
// A service cannot be managed by the dashboard and by IaC at the same time.
// There is no railway.json or railway.toml in this repository, so nothing has
// to be migrated before the 2026-12-01 cutoff that retires those files.

import { defineRailway, github, preserve, project, service } from "railway/iac";

const REPO = "Vele189/ClearSkies";

// Set explicitly. The SDK defaults an unspecified source branch to "main", and
// this repository's default branch is "master" - there is no "main" on the
// remote, so leaving it off points every service at a branch that is not there.
const BRANCH = "master";

// Watch patterns are gitignore-style and always anchored at the repository
// root, even for a service whose root directory is set. That is why each one
// repeats the service directory rather than being relative to it. Scoping
// them this way is what keeps a web-only commit from redeploying the API.

export default defineRailway(() => {
  // Railpack installs Python dependencies only when it finds requirements.txt,
  // uv.lock, poetry.lock, pdm.lock or a Pipfile. It detects Python from
  // pyproject.toml alone and sets a start command, but installs nothing, so the
  // build goes green and the container has no uvicorn in it. api/requirements.txt
  // exists for that reason and is kept in step with pyproject.toml by
  // scripts/check_requirements_sync.py. Do not delete it as a duplicate.
  const api = service("api", {
    source: github(REPO, { branch: BRANCH, rootDirectory: "/api" }),
    build: {
      watchPatterns: ["/api/**"],
    },
    start: "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    healthcheck: "/health",
    healthcheckTimeout: 30,
    env: {
      // The Neon branch's POOLED connection string (the `-pooler` hostname),
      // sealed in the dashboard; preserve() keeps an apply from clearing it. The
      // API opens many short connections and the pooler is what they are for.
      // Migrations do not run from this service: `make migrate` takes a
      // session-level advisory lock, which PgBouncer's transaction mode does
      // not hold, so it is run with the unpooled URL. See docs/database.md.
      DATABASE_URL: preserve(),
      // Without this the API falls back to http://localhost:5173 and the
      // deployed frontend is blocked by CORS.
      CORS_ORIGINS: "https://${{web.RAILWAY_PUBLIC_DOMAIN}}",
      PILOT_STATE: "LA",
      LOG_LEVEL: "info",
      // Absent in Phase 0; the draft endpoint reports 503 rather than failing
      // at import. Sealed in the dashboard when it is issued.
      //
      // The hard monthly spend cap is set on this key WITH THE PROVIDER, in the
      // OpenAI dashboard, and not here. A limit the application enforces is a
      // limit that stops working when the application has a bug, and the bug
      // that matters is the one that calls the API in a loop. docs/drafting.md
      // section 8 is the operator step.
      OPENAI_API_KEY: preserve(),
      // Which model writes drafts. Changing it invalidates the draft cache by
      // nothing at all — the cache keys on the methodology, corpus and prompt
      // versions, not the model — so a change here should be paired with a
      // deliberate cache clear if the old drafts are no longer wanted.
      DRAFT_MODEL: "gpt-4o",
      // Pinned to the corpus. Changing this without re-embedding gives vectors
      // from two models in one space, which returns quietly worse retrievals
      // rather than failing. See docs/corpus.md section 5.
      EMBEDDING_MODEL: "text-embedding-3-small",
    },
  });

  const web = service("web", {
    source: github(REPO, { branch: BRANCH, rootDirectory: "/web" }),
    build: {
      buildCommand: "npm ci && npm run build",
      watchPatterns: ["/web/**"],
    },
    // package.json start is `serve -s dist -l ${PORT:-3000}`. `serve` is
    // currently a devDependency, so the build must not prune dev dependencies
    // before the deploy stage.
    start: "npm start",
    env: {
      // Vite inlines VITE_ variables at build time, and the client joins this
      // onto a path, so it needs the scheme. RAILWAY_PUBLIC_DOMAIN is a bare
      // hostname.
      VITE_API_BASE_URL: "https://${{api.RAILWAY_PUBLIC_DOMAIN}}",
      // The PMTiles archive, on Cloudflare R2 rather than on this service.
      // Sealed in the dashboard once the bucket exists; preserve() keeps an
      // apply from clearing it. See infra/r2/README.md for why it is not here:
      // one large object read with Range requests is a poor fit for an edge
      // cache keyed on whole URLs, and Railway bills egress where R2 does not.
      // Whatever it is set to, the bucket's CORS policy must name this
      // service's public domain, and `make check-tiles URL=...` confirms it.
      VITE_TILES_URL: preserve(),
      // Free, no key, no attribution beyond the basemap's own. Overridden per
      // environment rather than hardcoded in the client.
      VITE_BASEMAP_STYLE: "https://tiles.openfreemap.org/styles/positron",
      // Place-name search stays off unless a geocoder is named. A deployment
      // should not send what people type into the search box to a third party
      // by default; coordinates and H3 indexes work without one.
      VITE_GEOCODER_URL: preserve(),
    },
  });

  return project("clearskies", { resources: [api, web] });
});
