# The API image.
#
# Nothing about this file is Railway-specific. It is what `docker compose up
# api` builds locally, what CI builds to prove the service still assembles, and
# what the deploy builds once the api repository is wired to a provider that
# reads a Dockerfile. .railway/railway.ts explains which of those is live.

FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: the layer is read-only in practice and .pyc files in
# it are dead weight. PYTHONUNBUFFERED: without it the logs sit in a pipe
# buffer and a crash takes the last few lines with it, which is exactly the
# lines that matter.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /srv

# requirements.txt and not `pip install .`, for the same reason the deploy reads
# it: it is the runtime list, without the dev extras, and it is kept in step
# with pyproject.toml by scripts/check_requirements_sync.py. Copied on its own
# so that a change to app/ reuses the installed layer instead of resolving
# every dependency again.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
# The migration runner lives in the image so that an operator can apply
# migrations from the same code the service runs -- `docker run --rm -e
# DATABASE_URL_UNPOOLED=... IMAGE python -m app.migrate up`. The service itself
# never runs them at startup: the runner takes a session-level advisory lock,
# which the pooled connection string cannot hold. See docs/database.md.
COPY migrations ./migrations

# An unprivileged, fixed uid. Fixed rather than assigned, so a bind-mounted
# volume has predictable ownership across rebuilds.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin clearskies
USER clearskies

EXPOSE 8000

# python rather than curl: the slim image has no curl, and adding one to the
# runtime image for a health check is a package to keep patched forever.
# /health answers while the database is down, which is the point of it -- so
# this proves the process is serving, not that the deployment is healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/health\",timeout=4)"]

# Shell form, because $PORT is assigned by the platform at run time and the
# exec form would pass the literal string. app/config.py reads a .env file when
# one is present; there is none in the image, and every setting comes from the
# environment.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
