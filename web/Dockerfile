# The frontend image: a Vite build served by nginx.
#
# THE IMAGE IS ENVIRONMENT-SPECIFIC. Vite inlines every VITE_ variable into the
# bundle at build time, so the API's URL, the tile archive and the basemap are
# baked in here and cannot be changed by the environment the container is
# started in. One image per deployment target, built with the build args below.
# The alternative -- a config.js written at container start and read through
# window -- would make the image portable at the cost of a network round trip
# before the first render and a source change in web/src/lib/api.ts. If that
# trade ever becomes the right one, docs/repos.md section 4 has the sketch.

FROM node:22-alpine AS build

# Node 20 reached end of life in April 2026 and Vite 8 wants >= 20.19 in any
# case. CI still pins node 20 in .github/workflows/ci.yml; when that moves, the
# two should move together.

WORKDIR /app

# The lockfile and manifest alone, so that a source-only change reuses the
# install layer. `npm ci` and not `npm install`: the point of the lockfile is
# that the image gets the versions CI tested, not whatever resolves today.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Defaults match web/vite.config.ts's dev server and app/config.py's CORS
# default, so a bare `docker build` produces an image that talks to an API on
# the host's :8000 -- useful for a smoke test, wrong for any deployment.
ARG VITE_API_BASE_URL="http://localhost:8000"
ARG VITE_TILES_URL=""
ARG VITE_BASEMAP_STYLE="https://tiles.openfreemap.org/styles/positron"
ARG VITE_GEOCODER_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_TILES_URL=$VITE_TILES_URL \
    VITE_BASEMAP_STYLE=$VITE_BASEMAP_STYLE \
    VITE_GEOCODER_URL=$VITE_GEOCODER_URL

# Railway passes a service's variables to the build as args when the Dockerfile
# declares them, and RAILWAY_ENVIRONMENT_NAME is always among them. A Railway
# build that still has the localhost default was deployed without
# VITE_API_BASE_URL set, and would ship a bundle calling the visitor's own
# machine -- fail here instead of after the deploy goes green.
ARG RAILWAY_ENVIRONMENT_NAME=""
RUN if [ -n "$RAILWAY_ENVIRONMENT_NAME" ] && [ "$VITE_API_BASE_URL" = "http://localhost:8000" ]; then \
      echo "VITE_API_BASE_URL is not set on this Railway service" >&2; exit 1; \
    fi

# `npm run build` is `tsc --noEmit && vite build`, so a type error fails the
# image rather than shipping a bundle CI would have rejected.
RUN npm run build


FROM nginx:1.27-alpine

# nginx rather than the `serve` package the Railway start command uses: serve is
# a devDependency, which means the deploy must be told not to prune dev
# dependencies before running, and it is a Node process held open to hand out
# static files. This stage carries no Node at all.

# The official image runs envsubst over /etc/nginx/templates/*.template at
# startup. The filter matters: without it envsubst would also expand anything
# else in the file that looks like a variable and happens to be set in the
# environment.
ENV PORT=8080
ENV NGINX_ENVSUBST_FILTER="^PORT$"

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# wget is in busybox here, so the health check costs nothing to install. It
# asks for the shell of the app, which is the only thing this container serves;
# whether the API behind it answers is the API's own health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --spider -q "http://127.0.0.1:${PORT}/" || exit 1
