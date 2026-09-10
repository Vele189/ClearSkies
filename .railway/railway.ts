// Railway infrastructure as code.
//
// STATUS: starting point, not yet verified against a live project.
// Run `railway config plan` to preview before `railway config apply`.
//
// The reliable path is the other direction: create the three services in the
// dashboard, set each Root Directory and Watch Paths, confirm a deploy, then
// run `railway config pull` to regenerate this file from what actually works.
// Watch paths and Dockerfile path are not in the published IaC reference, so
// they may need to be set in the dashboard and pulled back here.
//
// A service cannot be managed by the dashboard and by IaC at the same time.

import { defineRailway, github, project, service, volume } from "railway/iac";

const REPO = "OWNER/clearskies"; // replace with the GitHub repository

export default defineRailway(() => {
  // Postgres with PostGIS, h3 and pgvector. Built from infra/postgres/Dockerfile
  // so the extension set is version-controlled rather than a dashboard click.
  const db = service("db", {
    source: github(REPO, { rootDirectory: "/infra/postgres" }),
    volumeMounts: {
      "/var/lib/postgresql/data": volume("pgdata"),
    },
    env: {
      POSTGRES_USER: "clearskies",
      POSTGRES_DB: "clearskies",
      // POSTGRES_PASSWORD is set as a sealed variable in the dashboard.
    },
  });

  // Railpack installs Python dependencies only when it finds requirements.txt,
  // uv.lock, poetry.lock, pdm.lock or a Pipfile. It detects Python from
  // pyproject.toml alone and sets a start command, but installs nothing, so the
  // build goes green and the container has no uvicorn in it. api/requirements.txt
  // exists for that reason and is kept in step with pyproject.toml by
  // scripts/check_requirements_sync.py. Do not delete it as a duplicate.
  const api = service("api", {
    source: github(REPO, { rootDirectory: "/api" }),
    start: "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    healthcheck: "/health",
    healthcheckTimeout: 30,
    env: {
      DATABASE_URL: db.DATABASE_URL,
      PILOT_STATE: "LA",
      LOG_LEVEL: "info",
    },
  });

  // CDN is enabled on this service only. The API's draft endpoint returns
  // per-hex generated documents, so an edge cache in front of it buys nothing.
  const web = service("web", {
    source: github(REPO, { rootDirectory: "/web" }),
    build: "npm ci && npm run build",
    start: "npx serve -s dist -l $PORT",
    env: {
      VITE_API_BASE_URL: api.RAILWAY_PUBLIC_DOMAIN,
    },
  });

  return project("clearskies", { resources: [db, api, web] });
});
