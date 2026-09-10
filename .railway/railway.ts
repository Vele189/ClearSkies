// Railway infrastructure as code.
//
// STATUS: checked against the railway SDK (npm `railway`, v3.11.0) type
// definitions on 2026-09-11. It typechecks, and every field below exists in
// that schema. It has NOT yet been applied to a live Railway project: the
// three services still have to be created and a deploy confirmed before
// `railway config pull` can regenerate this file from reality.
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
// A service cannot be managed by the dashboard and by IaC at the same time.
// There is no railway.json or railway.toml in this repository, so nothing has
// to be migrated before the 2026-12-01 cutoff that retires those files.

import { defineRailway, github, preserve, project, service, volume } from "railway/iac";

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
  // Postgres with PostGIS, h3 and pgvector. Built from infra/postgres/Dockerfile
  // so the extension set is version-controlled rather than a dashboard click.
  // dockerfilePath is left unset on purpose: the Dockerfile sits at the default
  // location inside the root directory, so the DOCKERFILE builder finds it.
  const db = service("db", {
    source: github(REPO, { branch: BRANCH, rootDirectory: "/infra/postgres" }),
    build: {
      builder: "DOCKERFILE",
      watchPatterns: ["/infra/postgres/**"],
    },
    volumeMounts: {
      "/var/lib/postgresql/data": volume("pgdata"),
    },
    env: {
      POSTGRES_USER: "clearskies",
      POSTGRES_DB: "clearskies",
      // Set once as a sealed variable in the dashboard. preserve() tells an
      // apply to leave the existing value alone instead of clearing it.
      POSTGRES_PASSWORD: preserve(),
    },
  });

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
      // db builds its own image from a Dockerfile, so it is a plain service and
      // not a Railway managed database. Nothing hands it a DATABASE_URL, so the
      // DSN is composed here from the private domain. asyncpg takes a plain
      // postgresql:// DSN.
      DATABASE_URL:
        "postgresql://clearskies:${{db.POSTGRES_PASSWORD}}@${{db.RAILWAY_PRIVATE_DOMAIN}}:5432/clearskies",
      // Without this the API falls back to http://localhost:5173 and the
      // deployed frontend is blocked by CORS.
      CORS_ORIGINS: "https://${{web.RAILWAY_PUBLIC_DOMAIN}}",
      PILOT_STATE: "LA",
      LOG_LEVEL: "info",
      // Absent in Phase 0; the draft endpoint reports 503 rather than failing
      // at import. Sealed in the dashboard when it is issued.
      ANTHROPIC_API_KEY: preserve(),
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
    },
  });

  return project("clearskies", { resources: [db, api, web] });
});
