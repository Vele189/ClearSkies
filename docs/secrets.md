# Configuration and secrets

Every variable this project reads, what it is for, where it is set, and what
breaks without it. One config path covers local development, CI, the nightly
job, and the deployed services: all four read environment variables, and
nothing else.

This page is the register. `scripts/check_secrets.py` parses the table below and
fails CI if it drifts out of step with `.env.example` or with the workflows, so
a variable cannot be added in one place and forgotten in the others.

## The rule

**No credential value is ever committed.** `.env.example` holds placeholders and
is committed; `.env` holds values and is ignored. Nothing else in the repository
may contain a live credential, including test fixtures, docstrings, and
`docs/provenance.md`.

Secret scanning runs on every push and on the full history (see below), so this
rule is enforced rather than trusted.

## Register

Kind is `secret` if leaking it would let someone act as this project, `config`
if it is merely environment-specific, and `public` if it is compiled into the
frontend bundle and therefore visible to anyone who loads the page.

| Variable | Kind | Set in | Nightly ETL | Without it |
|---|---|---|---|---|
| `DATABASE_URL` | secret | local, actions, railway | required | The nightly job cannot write. The API still starts, serves `/health`, and reports the database as unavailable. |
| `POSTGRES_USER` | config | local | — | `docker compose` falls back to the value baked into the local image. |
| `POSTGRES_PASSWORD` | config | local | — | As above. Local container only; it is not the deployed credential. |
| `POSTGRES_DB` | config | local | — | As above. |
| `POSTGRES_PORT` | config | local | — | The container publishes on 5432, which collides with an existing local Postgres. |
| `CORS_ORIGINS` | config | local, railway | — | Defaults to the Vite dev origin, so the deployed frontend's requests are refused by the browser. |
| `LOG_LEVEL` | config | local, railway | — | Defaults to `info`. |
| `PILOT_STATE` | config | local, railway | — | Defaults to `LA`, which is the Phase 0 value anyway. |
| `ANTHROPIC_API_KEY` | secret | local, railway | — | The draft endpoint returns 503. Scores, the map, and every other endpoint are unaffected. |
| `OPENAQ_API_KEY` | secret | local, actions | optional | The OpenAQ adapter is skipped. Measured-monitor coverage goes missing, so the monitor-distance term of the confidence score degrades for every hex. Scores still compute. |
| `CENSUS_API_KEY` | secret | local, actions | optional | The ACS adapter falls back to the unkeyed quota of roughly 500 requests a day per address, which is not enough for a full tract pull. Expect the nightly job to fail partway. |
| `VITE_API_BASE_URL` | public | local, railway | — | The frontend calls `localhost:8000` and the deployed map shows no data. |
| `VITE_TILES_URL` | public | local, railway | — | The map renders basemap only, with no hexes. |
| `VITE_BASEMAP_STYLE` | public | local, railway | — | The map renders hexes over a blank background. |

### `VITE_` is not a place to put a secret

Vite inlines every `VITE_`-prefixed variable into the JavaScript bundle at build
time. They are readable by anyone who opens the page, and no amount of Railway
variable configuration changes that. If a browser feature ever appears to need a
credential, the credential belongs behind an API endpoint instead.

## Where each place is set

**Local.** `cp .env.example .env` and fill in what you need. Phase 0 needs
nothing filled in: every variable has a working local default, and the two
adapter keys are only read once Phase 1 wires the adapters.

**GitHub Actions.** Only the nightly ETL job consumes secrets. CI does not, and
must not: it runs on pull requests from forks, where secrets are unavailable by
design, and a CI job that needs a secret would fail for every outside
contributor.

```bash
gh secret set DATABASE_URL   --repo Vele189/ClearSkies   # required
gh secret set OPENAQ_API_KEY --repo Vele189/ClearSkies   # Phase 1
gh secret set CENSUS_API_KEY --repo Vele189/ClearSkies   # Phase 1
```

The workflow reads them through an `env:` block and calls
`scripts/check_secrets.py check --role etl` before doing any work. That preflight
prints which secrets are present and which are missing, never their values, and
fails only when a *required* one is absent. A missing optional key degrades that
adapter and lets the rest of the run proceed, which is the same posture the
methodology takes toward an upstream source going away (§11).

**Railway.** Set on the service that needs it, under Variables. `DATABASE_URL`
is not typed by hand: reference the database service with
`${{ Postgres.DATABASE_URL }}` so a credential rotation on the database
propagates without a redeploy of the API.

## Obtaining the Phase 1 adapter keys

| Key | Where | Cost |
|---|---|---|
| `OPENAQ_API_KEY` | Register at <https://explore.openaq.org/register>; the v3 API requires the key on every request | Free |
| `CENSUS_API_KEY` | Request at <https://api.census.gov/data/key_signup.html>; arrives by email | Free |

The other three sources need no credential. EPA ECHO, TRI via Envirofacts, and
AirToxScreen are all unauthenticated. That is worth stating explicitly, because
the natural assumption is that every adapter needs a key and it would be easy to
invent configuration for three sources that do not want any.

## Rotation

Rotate on a schedule of never, and immediately on any of: a contributor with
access leaving, a key appearing anywhere outside `.env`, or a scanning alert.

The order matters. **Revoke first, then replace.** A key that has been exposed is
compromised from the moment of exposure, and rewriting history does not
un-expose it: GitHub serves commits from forks and caches them, crawlers copy
public repositories within minutes, and a force-push cleans the branch while
leaving the object reachable. History rewriting is tidying, not remediation.

1. Revoke the old key at the provider.
2. Issue a new one.
3. Update `.env` locally, the Actions secret, and the Railway variable.
4. Re-run the nightly job with `workflow_dispatch` to confirm it still ingests.
5. Note the rotation and its reason in the pull request or issue that prompted it.

For `DATABASE_URL`, rotate the database credential in Railway; the API picks up
the new value through the service reference on its next deploy, and the Actions
secret must be updated by hand because it is a copy.

## Secret scanning

Two layers, because they catch different things at different times.

**In this repository.** `.gitleaks.toml` configures a scan that CI runs on every
push and pull request, over the working tree and over the full commit history.
It is version-controlled, runs on forks, and fails the build. Run it locally
with `make secrets`.

**On GitHub.** Secret scanning and push protection are free for public
repositories and are the only layer that can reject a push *before* the secret
reaches the remote, and the only one that receives GitHub's partner feed of
provider-validated patterns. Enable both at
<https://github.com/Vele189/ClearSkies/settings/security_analysis>, or:

```bash
gh api -X PATCH repos/Vele189/ClearSkies \
  -F security_and_analysis[secret_scanning][status]=enabled \
  -F security_and_analysis[secret_scanning_push_protection][status]=enabled
```

Confirm afterwards; the setting is not visible in the repository's files, so the
only evidence it is on is the API reporting it:

```bash
gh api repos/Vele189/ClearSkies --jq .security_and_analysis
```

## If a credential is exposed

1. **Revoke it.** Before writing an issue, before telling anyone, before
   cleaning the branch. Everything else can wait; this cannot.
2. Issue a replacement and update the three places above.
3. Check the provider's audit log for use between exposure and revocation.
4. Open an issue recording what leaked, when, how, and what the log showed.
   Name the gap that let it through, and close it. The point is the fix, not the
   blame.
5. Only then consider rewriting history, understanding that it changes nothing
   about the exposure and is worth doing only to stop the value being copied
   again from a fresh clone.
