import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import * as schema from "./schema.js";

// App traffic goes through the pooled URL.
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  // Allow for compute cold starts after scale-to-zero.
  connectionTimeoutMillis: 15_000,
});

export const db = drizzle(pool, { schema });
export { schema };
