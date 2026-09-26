# Repositories and containers

Three repositories, one source of truth. This one holds everything and is where
every change is made. Two others — `ClearSkies-web` and `ClearSkies-api` — hold
the frontend and the API on their own, so each deploys from a repository whose
whole contents are that service, and they are generated from this one rather
than edited.

Both services are containers. `api/Dockerfile` and `web/Dockerfile` live here,
in the directories they build, which is what makes them arrive at the root of
the split repositories without anything copying them.

## 1. What is where

```
ClearSkies/                     this repository — edit here
├── api/                        FastAPI service   ─split→  ClearSkies-api/
│   ├── Dockerfile                                         ├── Dockerfile
│   ├── app/  migrations/                                  ├── app/  migrations/
│   └── .env.example                                       └── .env.example
├── web/                        React + MapLibre  ─split→  ClearSkies-web/
│   ├── Dockerfile                                         ├── Dockerfile
│   ├── nginx.conf.template                                ├── nginx.conf.template
│   └── src/  .env.example                                 └── src/  .env.example
├── etl/ scoring/ assistant/    the pipeline and the paper — here only
├── infra/postgres/             the local database image — here only
├── docs/ scripts/ Makefile     here only
└── docker-compose.yml          db, plus api and web behind the `app` profile
```

The pipeline, the scoring package, the statute corpus and the methodology stay
here. They are not a backend in the sense that the split means: nothing in
`api/` imports them, and they are tied to `docs/methodology.md` far more
tightly than to the service.

## 2. Why mirrors and not submodules

A submodule would make each service independently editable, at the price of a
pointer commit for every change and a detached HEAD for anyone who forgets to
`--recurse-submodules`. Almost every change here touches a service and its
documentation, or a service and a migration, and a submodule splits that into
two commits in two repositories that have to land in order.

Mirroring keeps one commit and one review. The cost is that the deploy
repositories are downstream: a commit made directly in one is not carried back,
and section 3 says what to do if that happens.

## 3. Syncing

```
make split                      both, from the current branch
./scripts/split-repos.sh web    one of them
make split BRANCH=master        from a named branch
```

`git subtree split` rewrites the commits that touched `web/` or `api/` into a
history whose root is that directory, then the script creates the repository or
merges the new commits into it. It is deterministic: the same monorepo history
produces the same commit ids every time, which is what lets the second run be an
ordinary merge rather than an unrelated history. Neither repository is pushed by
the script; both have a single remote, `mono`, pointing at this working copy.

The script creates each repository with one remote, `mono`, pointing at this
working copy. The GitHub remotes are added by hand, once:

| Local directory | GitHub |
|---|---|
| `../ClearSkies-web` | [Vele189/clearskies-web](https://github.com/Vele189/clearskies-web) |
| `../ClearSkies-api` | [Vele189/clearskies-api-](https://github.com/Vele189/clearskies-api-) |

The API's slug ends in a hyphen. It is not a typo here or in
`.railway/railway.ts`; the repository is named `clearskies-api-`, and writing it
the way it looks like it should be written points at nothing. Rename it on
GitHub if it grates, and move both references with it.

After that, a release is:

```
make split
git -C ../ClearSkies-web push
git -C ../ClearSkies-api push
```

**A commit made in a deploy repository.** The next sync merges the monorepo's
version over it, so it is not lost but it is also not in the history that
matters. Bring it back with `git subtree pull`:

```
git subtree pull --prefix=web ../ClearSkies-web master --squash
```

Then commit here, re-split, and the two agree again. Doing this routinely turns
the arrangement into a two-way sync, which is the thing this layout is trying
not to be.

## 4. The images

**`api/Dockerfile`** installs `requirements.txt` into a `python:3.12-slim` and
runs uvicorn as an unprivileged user. `requirements.txt` and not the
`pyproject.toml` extras: it is the runtime list, `scripts/check_requirements_sync.py`
keeps the two in step, and copying it on its own means a change under `app/`
reuses the installed layer. The migration runner is in the image so an operator
can apply migrations from the same code the service runs, but nothing applies
them at startup — the runner's advisory lock is session-level and the pooled
connection string cannot hold it. See [database.md](database.md).

**`web/Dockerfile`** builds with Node and serves with nginx, which leaves no
Node in the runtime image at all. `serve`, which the previous Railway start
command used, is a devDependency, so that arrangement required a build that
never pruned dev dependencies.

**The frontend image is environment-specific.** Vite inlines every `VITE_`
variable into the bundle at build time, so the API's URL and the tile archive
are fixed when the image is built, and the Dockerfile takes each as a build arg.
Pointing the app at a different API means rebuilding, not restarting. The
alternative is a `/config.js` written by the container's entrypoint from its
environment and read through `window` in `web/src/lib/api.ts`; it would make one
image portable across environments, at the cost of a blocking request before the
first render and a config object that can be wrong at run time rather than at
build time. Build args are the right trade while there is one deployment.

**Locally:**

```
make images        build both without starting anything
make stack         database, API and frontend as containers
make stack-logs    follow the two application containers
make stack-down    stop it all, keeping the database volume
```

`api` and `web` sit behind the compose `app` profile, so `make up` and CI's
database job still start the database alone. Inside the compose network the
database is `db`, not `localhost`: the `DATABASE_URL` in a root `.env` that
works for `make api` on the host does not work in the container, which is why
the compose file sets its own and reads `CLEARSKIES_DOCKER_DATABASE_URL` when
you want that container pointed at a Neon branch instead.

CI builds both images on every pull request and calls `/health` on one and the
app's shell and a client-side route on the other. A Dockerfile that is never
built is a Dockerfile that is broken, and a deploy is a poor place to find out.

## 5. What is duplicated

`api/.env.example` and `web/.env.example` restate the settings each service
reads, because a split repository has no parent `.env` to symlink to and no
sibling to borrow the combined `../.env.example` from. In this repository they
are redundant: `api/.env` and `web/.env` are symlinks to the root `.env`.

Nothing checks that the three files agree. A guard would have to parse three
formats of comment-heavy example file to decide what counts as drift, and the
failure it prevents — a missing variable falling back to the default in
`api/app/config.py` — is loud in a deployment and harmless locally. The rule is
the ordinary one: a setting added to `config.py` is added to both.

The database image is **not** duplicated. `infra/postgres` stays here, and the
api repository's compose file builds it from this repository over git rather
than carrying a copy, so there is one Dockerfile compiling h3-pg and one place
to change it.

## 6. The deploy

`.railway/railway.ts` names one repository per service and no longer sets a
root directory or watch patterns: each repository is the service, so a frontend
commit cannot redeploy the API. Both services build from their Dockerfile,
which Railway prefers when it finds one, and neither sets a start command —
that would override the image's `CMD`, and then the command lives in two places.

A change reaches production when the split is pushed, not when it is committed
here. That is a deliberate gap: the monorepo's CI is what says a change is fit
to deploy, and the push is the act that deploys it.
