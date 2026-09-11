# Tile hosting: Cloudflare R2

The map reads one PMTiles archive with HTTP Range requests. It lives in an R2
bucket, not on the Railway frontend service, and `VITE_TILES_URL` points at it.

## Why not Railway

Two reasons, and the first is the one that would bite quietly.

PMTiles is a single large object read in pieces. An edge cache keyed on whole
URLs has nothing useful to do with that: it either misses on every Range request
or caches the entire archive in order to serve a kilobyte of it. Railway's CDN
is such a cache.

And Railway bills egress at $0.05/GB where R2 charges nothing for it. A map that
pulls a few hundred kilobytes per visitor is cheap either way until it is not,
and the archive is the largest thing this project serves.

## Bucket setup

Once, by hand, and then never again:

1. Create an R2 bucket, e.g. `clearskies-tiles`.
2. Enable public access, or attach a custom domain such as
   `tiles.clearskies.example`. A custom domain is preferable: it survives a
   bucket rename and it keeps the URL out of the account-specific
   `*.r2.dev` namespace.
3. Apply the CORS policy in `cors.json`:

   ```bash
   aws s3api put-bucket-cors \
     --endpoint-url "https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com" \
     --bucket clearskies-tiles \
     --cors-configuration file://infra/r2/cors.json
   ```

4. Set `VITE_TILES_URL` on the Railway web service to the archive's URL.

`AllowedOrigins` in `cors.json` lists the deployed frontend and the Vite dev
server. `Range` has been a CORS-safelisted request header since 2022, so a
simple single-range request does not preflight, but it is listed anyway because
a client that sends `If-Match` alongside it does, and a preflight that fails
looks identical to a missing archive.

`ExposeHeaders` matters more than it looks. `Content-Range` and `Content-Length`
are not readable cross-origin unless the bucket says so, and a PMTiles client
that checks them fails in a way that reads as a corrupt archive rather than as a
missing header.

## Publishing a build

```bash
make tiles SCORES=run.json          # build the archive
make deploy-tiles ARCHIVE=tiles/clearskies-la.pmtiles
make check-tiles URL=$VITE_TILES_URL
```

`deploy-tiles` uploads with the AWS CLI against the R2 endpoint, since R2 speaks
S3. `check-tiles` then asks the published URL the questions a browser will ask:
that it answers 206 to a Range request rather than sending the whole archive,
that the CORS origin comes back, that `Content-Range` is exposed, and that the
bytes it returns really are the head of a PMTiles v3 file.

That last step is not ceremony. A host that ignores `Range` and answers 200 with
the full body leaves the map working perfectly while pulling the entire archive
on every page load, which is invisible in a browser and visible only in a bill.

## Credentials

`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `CLOUDFLARE_ACCOUNT_ID`, from an
R2 API token scoped to this bucket. They belong in the deploy environment and in
`.env` locally; nothing in the application reads them, because nothing in the
application writes tiles.
