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

# 4. First boot writes a one-time initial admin token to an owner-only
#    file. The log names the path and never carries the token itself.
docker compose logs core

# 5. Attach your CLI (verifies the server and token before persisting
#    anything), then remove the file — it is the only copy.
yoke connect http://127.0.0.1:8765 --token-stdin < secrets/first-boot-admin-token
rm secrets/first-boot-admin-token

# 6. Confirm the machine is wired up. This fails if the server is not
#    answering, so a green run means the whole path works.
yoke status
```

The token file is bind-mounted into the core service, and the container
writes through a descriptor the root bootstrap opened before dropping
privileges — so the credential reaches a file you own without ever passing
through `docker compose logs`. `yoke self-host init` creates the file, so
run `--protect-existing` on any bundle that predates it.

`yoke self-host init` takes `--dir`, `--port`, and `--image` overrides. By
default it resolves the installed CLI's immutable release manifest and writes
that release's exact `ghcr.io/upyoke/yoke-server:<sha12>` image to `.env`.
Every fresh bundle therefore starts with matching CLI and server versions, and
a later container restart keeps the same server. `--image` remains an explicit
operator override. Generated credentials ride mounted files under `secrets/`
rather than `.env`, whose values Compose `$`-interpolates.

Protect older bundles in place without rewriting `.env`, Compose, or database credentials:

```bash
yoke self-host init --dir /path/to/yoke-server --protect-existing
```

The command preserves operator-authored `.gitignore` rules and reports that credentials were not regenerated. The bundle and `secrets/` must be real operator-owned directories; `secrets/` must be mode `0700`. It refuses symlinked paths and secrets already tracked by Git. Remove reported paths from the index, rotate any exposed credential, and retry.

## Move an existing universe here

Point the import at a fresh or replaceable bundle, keep `core` stopped, and protect the archive as private control-plane data:

```bash
yoke self-host init --dir /path/to/yoke-server
chmod 600 ~/Downloads/acme-universe-20260714T120000Z.tar
yoke self-host import ~/Downloads/acme-universe-20260714T120000Z.tar \
  --dir /path/to/yoke-server
```

The tar carries the database dump and freeze receipt (see [Universe portability](universe-portability.md)); that receipt supplies checksum verification. Type `replace` at the prompt, or pass `--yes` for a non-interactive replacement.

The command requires Docker with Compose, validates the bundle, and refuses while `core` runs. The archive must be a current-owner, single-link regular file with no group/world access. Compose starts only the database and streams the archive to a one-off process in the pinned image; it never bind-mounts the host archive.

Uploaded DDL never runs. Yoke creates the trusted destination schema, validates the bounded archive, and restores approved data and sequences in one transaction; retry replaces a failed or interrupted attempt.

Archives can contain raw capability secrets plus hashed credentials. Keep them owner-only and rotate secrets when custody changes. Restore revokes imported API tokens and browser sessions, grants neutral `admin` org-admin access, and mints one replacement token. Save its one-time success output, then run the printed `docker compose up -d core` and `yoke connect` steps.

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

The server can optionally offer a browser sign-in door backed by your
identity provider, with deliberately read-only browser sessions. The
walkthrough — provider registration, bundle wiring, and who gets in —
is [Browser Sign-In](self-host-browser-sign-in.md).

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
health, so onboarding offers disabled. Partial or invalid public settings
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

Running bundles stay on their exact image pin until you deliberately advance
the pair. From any directory, run:

```bash
yoke self-host upgrade --dir /path/to/yoke-server
```

The command performs a read-only preflight and shows the current image, target
release, exact target image, and ordered actions before asking you to type
`upgrade`. It then installs that release's CLI through the public installer
channel, atomically rewrites `YOKE_SERVER_IMAGE`, runs `docker compose pull
core`, and runs `docker compose up -d`. Use `--yes` only when an automated run
has already accepted that same plan.

Failures name the stage and exact retry. The pin is unchanged when CLI install
fails; after the CLI and pin advance, a pull or restart failure leaves both
durable identities on the target and prints the two Compose recovery commands.
On every boot the entrypoint converges additive schema before serving;
data-transforming changes still use Yoke's governed migration runner. Confirm
the running source identity through the `build` field on `GET /v1/health`.

## Take it back off

`yoke self-host teardown` removes the install. It always stops and removes the
stack; everything further is opt-in and named for what it destroys:

```bash
cd yoke-server
yoke self-host teardown                       # stop the stack; keep the data
yoke self-host teardown --remove-images \
  --remove-bundle --destroy-universe          # remove everything, prompts first
```

Without `--destroy-universe` the `pgdata` volume survives, so
`docker compose up -d` brings the same universe back. With it, the volume and
every item, event, and credential in it are gone; the command asks for consent
unless you pass `--yes`. `--remove-images` removes the images this bundle uses
and reports any another container still needs. `--remove-bundle` deletes the
files Yoke wrote, `secrets/` and the admin token file included, and reports
anything else in the directory rather than deleting it.

Teardown also retires the machine connection pointing at this bundle's server,
so no dead authority is left behind. Pass `--keep-connection` to leave it, or
`--activate ENV` to name which connection takes over as this machine's
authority. The same retirement is available on its own as
`yoke connection remove ENV [--activate ENV]`; removing your last connection
leaves the machine unconfigured, which `yoke status` then reports.

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
