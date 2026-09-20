# ClearSkies database image.
#
# One Postgres with every extension the project needs:
#   postgis   spatial types and operations
#   h3        hexagonal indexing, built from source (no PGDG package exists)
#   vector    pgvector, for the statute corpus embeddings
#
# h3-pg is the reason this image exists. Managed Postgres providers generally do
# not offer it, which is what put the database on Railway rather than a free
# managed tier. The ETL computes H3 indexes in Python and stores them, so the
# pipeline does not depend on this extension; it is here for ad-hoc SQL.
#
# Base is postgres:17-bookworm rather than a postgis/postgis tag: those images
# are still built on Debian bullseye, whose security suite is end-of-life, and
# `apt-get update` fails on the expired Release file.

FROM postgres:17-bookworm

ARG PG_MAJOR=17

# Pinned for reproducibility. Bump deliberately, not automatically.
ARG H3_PG_REF=refs/tags/v4.2.3

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        cmake \
        postgresql-server-dev-${PG_MAJOR} \
        postgresql-${PG_MAJOR}-postgis-3 \
        postgresql-${PG_MAJOR}-postgis-3-scripts \
        postgresql-${PG_MAJOR}-pgvector; \
    \
    mkdir -p /tmp/h3-pg; \
    curl -fsSL "https://codeload.github.com/zachasme/h3-pg/tar.gz/${H3_PG_REF}" \
        | tar xz -C /tmp/h3-pg --strip-components=1; \
    cd /tmp/h3-pg; \
    # CMake fetches the H3 C library itself, pinned by hash in cmake/h3.
    #
    # PostgreSQL_INDENT is switched off deliberately. h3-pg auto-detects
    # pgindent and makes source formatting a build dependency of the library,
    # which fails in a container because pgindent wants a typedefs file it has
    # no way to download. Formatting is a contributor convenience, not part of
    # producing the extension.
    cmake -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DPostgreSQL_INDENT=OFF; \
    cmake --build build; \
    cmake --install build; \
    \
    cd /; \
    rm -rf /tmp/h3-pg; \
    apt-get purge -y --auto-remove \
        build-essential cmake curl postgresql-server-dev-${PG_MAJOR}; \
    rm -rf /var/lib/apt/lists/*

COPY initdb/ /docker-entrypoint-initdb.d/
