import { defineConfig } from "drizzle-kit";

try {
  process.loadEnvFile(".env.local");
} catch {
  // Env already provided (CI, `neon-env run`, etc.)
}

// Migrations need a direct (non-pooled) connection; PgBouncer's
// transaction mode breaks session-level DDL.
const url = process.env.DATABASE_URL_UNPOOLED;
if (!url) throw new Error("DATABASE_URL_UNPOOLED is not set");

export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  dbCredentials: { url },
  // PostGIS owns these; keep drizzle-kit from trying to manage them.
  extensionsFilters: ["postgis"],
  strict: true,
  verbose: true,
});
