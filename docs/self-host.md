# Self-Host Yoke

Run the Yoke API server on your own host: one `docker compose` bundle carrying
the published server image plus a Postgres 17 database. Your data stays on
hardware you control; engineers point their CLIs at your server instead of the
hosted platform.

## Quickstart

On the server host (needs Docker with the compose plugin):

```bash
# 1. Install the CLI (also how engineer machines install it later).
curl -fsSL https://upyoke.com/install | sh

# 2. Materialize the compose bundle. Writes docker-compose.yml, .env,
#    and generated database credentials as owner-only secret files —
#    the generated password is never printed. A marked block in
#    .gitignore protects .env and secrets/ without replacing your rules.
yoke self-host init

# 3. Start the server.
cd yoke-server && docker compose up -d

# 4. First boot prints a one-time initial admin token. Read it from the
#    core service log and store it somewhere safe — it is not shown again.
docker compose logs core

# 5. Attach your CLI (verifies the server and token before persisting
#    anything; paste the admin token on stdin).
yoke connect http://127.0.0.1:8765 --token-stdin

# 6. Confirm the machine is wired up.
yoke status
```

`yoke self-host init` takes `--dir`, `--port`, and `--image` overrides;
the defaults come from one place (`yoke_contracts.server_image`, today
`ghcr.io/upyoke/yoke-server:latest`) so the bundle always tracks the
published image. Knobs live in the bundle's `.env`; generated
credentials ride mounted secret files under `secrets/` — never `.env`,
whose values compose `$`-interpolates.

Bundles created before the managed ignore block can be protected in place,
idempotently, without rewriting `.env`, Compose configuration, or database
credentials:

```bash
yoke self-host init --dir /path/to/yoke-server --protect-existing
```

The command preserves every operator-authored `.gitignore` rule outside its
marked Yoke-owned block and reports explicitly that database credentials were
not regenerated. The bundle and `secrets/` must be real directories owned by
the operator; `secrets/` must have mode `0700`. Run
`chmod 700 /path/to/yoke-server/secrets` if needed. It refuses symlinked secret
paths and also refuses if Git already tracks `.env` or a file under `secrets/`:
ignore rules cannot remove an indexed secret. Remove the reported paths from
the Git index, rotate any credential that entered history, then retry the
protection command.

## Move an existing universe here

Point the import at a bundle (a fresh one, or an existing one whose universe
you are replacing), but do not start its `core` service. Protect the portable
archive as private control-plane data, then import it from outside or inside
the bundle directory:

```bash
yoke self-host init --dir /path/to/yoke-server
chmod 600 ~/Downloads/acme-universe-20260714T120000Z.tar
yoke self-host import ~/Downloads/acme-universe-20260714T120000Z.tar \
  --dir /path/to/yoke-server
```

The archive is one tar carrying the database dump and its freeze receipt
(see [Universe portability](universe-portability.md)); checksum verification
is derived from the receipt inside it. The command asks exactly one thing
beyond the file: consent to replace whatever universe the bundle's database
currently holds (type `replace` at the prompt, or pass `--yes` for
non-interactive runs).

The command requires Docker with Compose, validates the existing bundle, and
refuses while its `core` service is running. It opens the archive without
following symlinks and requires a current-owner, single-link regular file with
no group or world access. Compose starts only the database, then streams the
archive over stdin to a one-off process in the pinned server image; the host
archive is never bind-mounted into a container.

Uploaded DDL is never run: Yoke resets the destination, creates the trusted
schema from the destination image, validates the bounded archive, and restores
only approved table data and sequence values inside one transaction. A failed
or interrupted attempt is simply replaced by the next run.

A whole-universe archive can contain portable capability secrets in raw form,
alongside hashed API and browser credential records. Keep the archive
owner-only at every hop, and review or rotate capability secrets when custody
changes between platforms. The import does not preserve API or browser access:
in the same transaction as the data restore, it revokes every active imported
API token and browser session, grants the neutral `admin` actor the org admin
role, and mints one replacement token. Save the token from the success block
immediately: it is shown once and never stored or reprinted. Then run the
printed `docker compose up -d core` and `yoke connect` steps.

If the restore reported success but its one-time result was lost before you
could save it, mint a recovery credential while `core` remains stopped:

```bash
cd /path/to/yoke-server
docker compose run --rm core --recover-import-credential
```

Save that command's `raw_token`, then start the service. Recovery atomically
revokes every prior import/recovery credential before minting its replacement,
so it is safe to repeat if another one-time result is lost.

## Export over the server connection

After `yoke connect` selects this self-host server, an org administrator can
stream a portable archive without acquiring its database DSN:

```bash
yoke universe export --out ~/backups/
```

The CLI sends its bearer token only to the configured server, refuses
redirects, requires the archive media type, enforces the portability size and
time bounds, and publishes the owner-only destination file atomically. The
generated Compose bundle marks the runtime with
`YOKE_SERVER_MODE=self-host`; without that explicit marker the core endpoint
is hidden. Hosted Platform tenants continue through Platform's
fleet-coordinated download route instead of this self-host boundary.

By default the API publishes on loopback only (`127.0.0.1:8765`). To
serve your network, edit `YOKE_API_PUBLISH` in `.env` (for example
`0.0.0.0:8765`) and put TLS in front — see the operator notes below.

## Engineer machines

Each engineer runs the same installer, then attaches to your server
with a token you mint for them:

```bash
curl -fsSL https://upyoke.com/install | sh
yoke connect https://yoke.internal --token-stdin
yoke status
```

`yoke connect` requires `https://` for every network server. Terminate TLS at
your reverse proxy and give engineers its HTTPS URL. Plain `http://` is
accepted only for a numeric loopback endpoint such as `127.0.0.1`, so local
host setup works without sending an actor token over the network. The command
refuses to persist anything until the server answers `/v1/health` and the
token passes `/v1/auth/identity`.

Minting additional tokens is an admin operation on the server host
(operator-shaped surface today):

```bash
docker compose exec core python3 -m yoke_core.domain.api_tokens_cli \
  mint --actor <actor-id> --name <engineer-label>
```

## Browser sign-in (OIDC)

Optionally, the server can offer a browser sign-in door backed by your
identity provider — anything that speaks OpenID Connect with discovery
(Okta, Keycloak, Microsoft Entra ID, Google Workspace, ...). Browser
sessions are deliberately **read-only**: a signed-in browser sees the
landing page; every write still requires an API token over
`Authorization: Bearer`. Leaving the door unconfigured changes nothing
for tokened clients — the OIDC routes simply answer 409.

**1. Register a client at your provider.** Create a confidential "web
application" client with the authorization-code flow, scopes
`openid email profile`, and this redirect URI (your server's external
base URL plus the fixed callback path):

```text
https://yoke.internal/v1/auth/oidc/callback
```

**2. Wire the bundle.** In the bundle directory, write the client
secret as an owner-only file and enable the commented blocks:

```bash
printf '%s\n' '<client-secret>' > secrets/oidc-client-secret
chmod 600 secrets/oidc-client-secret
```

Then uncomment the OIDC lines in `.env` (`YOKE_OIDC_ISSUER`,
`YOKE_OIDC_CLIENT_ID`, `YOKE_OIDC_REDIRECT_URL`,
`YOKE_OIDC_CLIENT_SECRET_FILE`) and the two `yoke-oidc-client-secret`
blocks in `docker-compose.yml`, and `docker compose up -d`. Setting
some vars but not all fails loudly: the door answers 409 naming what is
missing.

The Compose service mounts the owner-only source secret as root, copies it into a container-private tmpfs as mode `0600` owned by the image's `yoke`
user, rewrites the file binding, seals the original mount directory as
root-only, clears supplementary groups, and drops to that user before starting
the server. Every source must be a read-only mount; this also handles Compose
implementations that normalize the in-container source-file mode. The same
bootstrap protects the core database DSN and optional GitHub App key; host
copies remain owner-only.
Compose drops every ambient container capability, grants only the three needed
for this handoff (`CHOWN`, `SETGID`, and `SETUID`), enables
`no-new-privileges`, and the bootstrap refuses to start the server if any
effective Linux capability remains after the drop. The Compose healthcheck
uses the same immediate drop, so the service-level root override does not leave
periodic root healthcheck processes running beside the server.

**3. Decide who gets in.** Visiting `https://yoke.internal/` offers
"Sign in"; after the provider round-trip the server admits the verified
identity by the first matching rule:

1. **Already linked** — the identity (issuer + subject) was linked to an
   actor by a previous sign-in or an admin pre-link.
2. **Pending invite** — a pending invite matches the verified email
   (case-insensitive); accepting it links the identity and grants the
   invite's org role, if one was set.
3. **Auto-join domain** — the verified email's domain equals the org's
   auto-join domain; a new member actor is created with no role grant.
4. Otherwise the sign-in is **refused** with an operator-facing reason.

Admission administration is org-admin surface on the `yoke` CLI:

```bash
yoke identity invite create pat@corp.example --role admin
yoke identity invite list --status pending
yoke identity invite revoke <invite-id>
yoke identity autojoin set corp.example      # or: --clear
yoke identity link set --actor <actor-id> --issuer <iss> --subject <sub>
yoke identity link set --actor <actor-id> --email pat@corp.example
```

Email trust is strict by default: invites and auto-join match only when
the provider marks the email verified. For providers that omit the
`email_verified` claim entirely, opt in with
`YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL=true` (an explicit `false` from the
provider is never trusted).

## GitHub App server automation

GitHub automation uses an operator-owned App and key dedicated to the self-hosted
server, never an upyoke Product App or Yoke Development. Configure its URLs on the
server's HTTPS origin. Project rows store verified installation/repository
bindings; the App private key is never stored in `capability_secrets` or any
per-project setting.

Registration, least-privilege installation scope, hosted secret ownership,
dual-key rotation, and incident response are defined in
[GitHub App Operations](github-app-operations.md). Use that runbook before
creating the runtime file below.

When the same App also serves engineer-machine authorization, enable **Device
Flow** and **Expire user authorization tokens** in its registration before
connecting any machine. The first enables browser device authorization; the
second supplies the expiring access token, refresh token, and expiries that the
local credential store requires. Use the baseline repository grant in the
operations runbook.

Install the downloaded App private key through Yoke's owner-only ingress. From
outside the bundle, run:

```bash
chmod 600 /secure/path/app-key.pem
yoke self-host init --dir /path/to/yoke-server --protect-existing \
  --github-app-private-key /secure/path/app-key.pem
```

The source must be a real, single-link regular file owned by the current user
with no group/world access. The command opens it once without following
symlinks, validates a nonempty private-key-shaped PEM, writes a mode `0600`
temporary file in the bundle's `secrets/` directory, fsyncs it, atomically
replaces `github-app-private-key.pem`, and fsyncs the directory. Rotation never
publishes a partial key and never regenerates the bundle's database credentials.

Then set these non-secret/runtime bindings in `.env`:

```text
YOKE_GITHUB_APP_ISSUER=<numeric-app-id>
YOKE_GITHUB_APP_API_URL=https://api.github.com
YOKE_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/yoke-github-app-private-key

# Optional product-facing Connect GitHub profile; set all four or none.
YOKE_GITHUB_APP_WEB_URL=https://github.com
YOKE_GITHUB_APP_ID=<numeric-app-id>
YOKE_GITHUB_APP_CLIENT_ID=<public-client-id>
YOKE_GITHUB_APP_SLUG=<app-slug>
```

Uncomment the `yoke-github-app-private-key` service mount and top-level secret
definition in `docker-compose.yml`, then run `docker compose up -d`. The
bundled GitHub App block is disabled until all three values and the mounted key
are present. GitHub Enterprise Server uses its HTTPS API origin in
`YOKE_GITHUB_APP_API_URL`; redirects to another origin are rejected.
The key stays mode `0600` in the host bundle. The self-host bootstrap copies it
to the core service's private tmpfs with runtime-user ownership before dropping
root; it never weakens the host file to make a bind mount readable.
The public profile is all-or-none. Whenever private App configuration is
present, startup performs one bounded, no-redirect App identity check—even
when the public profile is omitted. Missing, partial, unreadable, or identity-
mismatched public configuration remains a detail-free `available: false` in
health, so onboarding offers backlog-only. Partial or invalid public settings
also emit a value-free startup warning that tells the operator to set every
public field consistently or unset all of them. Health never performs a network
request. After repairing a key or identity mismatch, restart the core service
so startup can attest the repaired authority before it is advertised.

Hosted/stage deployments use the same runtime contract but source the key from
AWS Secrets Manager. The deploy environment's `environments.settings` contains
only this non-secret reference block:

```json
{
  "github_app": {
    "issuer": "<numeric-app-id>",
    "api_url": "https://api.github.com",
    "private_key_secret_arn": "arn:aws:secretsmanager:<region>:<account>:secret:<name>",
    "public": {
      "client_id": "<public-client-id>",
      "app_slug": "<app-slug>",
      "app_id": 123456,
      "web_url": "https://github.com"
    }
  }
}
```

Omit `public` for a private/operator-only App that must never become the
default machine Connect profile. If `public` is present it must be complete;
the outer `api_url` is its single API-origin authority.

The origin instance role resolves that ARN locally. Deployment writes
`github-app-private-key.pem` as mode `0640`, owned by the deploy user and a
dedicated host secrets group, and grants only that numeric supplemental group
to the non-root container that mounts it at
`/run/secrets/yoke-github-app-private-key`. Secret values never cross SSH and
are not placed in Compose environment variables, command arguments, Pulumi
state, or project-engine databases.

## Upgrades

The server image is versioned by tag; on every boot the entrypoint converges the full
idempotent core schema before serving (all tables, indexes, AND additive columns), so
every net-new additive table or column the deployed code expects self-propagates to
your already-born database — no manual migration step is needed for additive schema.
(Data-transforming changes — backfills, drops, rewrites — still go through Yoke's
governed migration runner.) An upgrade is therefore a pull plus a restart:

```bash
cd yoke-server
docker compose pull core
docker compose up -d
```

To pin instead of tracking `latest`, set `YOKE_SERVER_IMAGE` in `.env`
to a sha-tagged reference and re-run `docker compose up -d`. Confirm
which code is answering via the `build` field on `GET /v1/health`.

## You own the operations

Self-hosting trades the hosted platform's operations for control:

- **Uptime is yours.** The bundle restarts containers on failure
  (`restart: unless-stopped`), but host maintenance, monitoring, and
  capacity are on you.
- **Backups are yours.** All state lives in the `pgdata` volume; use
  `yoke universe export` for portable archives and retain regular Postgres or
  volume snapshots for infrastructure-level recovery before upgrades and on a
  schedule.
- **TLS is yours.** The server speaks plain HTTP; anything beyond
  loopback belongs behind a TLS-terminating reverse proxy you operate,
  with the API published only where you intend engineers to reach it.
