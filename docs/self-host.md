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
yoke self-host init --start
cd yoke-server

# 3. First boot writes the reusable administrator token to an owner-only
#    file. The log names the path and never carries the token itself.
docker compose logs core

# 4. Attach your CLI (verifies the server and token before persisting
#    anything), then remove the file — it is the only raw copy on disk.
#    The token itself stays valid until you revoke it.
yoke connect http://127.0.0.1:8765 --token-stdin < secrets/first-boot-admin-token
rm secrets/first-boot-admin-token

# 5. Confirm the machine is wired up. This fails if the server is not
#    answering, so a green run means the whole path works.
yoke status
```

The host command opens each mode `0600` input as its non-root operator and
streams it on stdin through Docker exec. The container drops to its runtime
user and writes private tmpfs copies; no host file is mounted or chowned and
no credential is placed in an environment variable. The admin token returns
over that same private handoff, outside Docker logs; the host atomically writes
its owner-only token file and acknowledges durable storage before token creation
commits. A failed handoff refuses with a reason and retry command.

Start/restart an existing bundle with `yoke self-host init --dir PATH
--protect-existing --start`. This refreshes the packaged Compose template,
preserving `.env`, database credentials, and the Postgres volume. Keep runtime
settings in `.env`; reapply any custom Compose changes after a template refresh.
Automatic container restart is disabled: after a host/daemon restart, run that
host command again so it can reopen the protected inputs. Raw Compose starts
alone cannot supply the handoff. Native Ubuntu rootful Docker is exercised by
the manual bootstrap probe; rootless Docker and Fedora/SELinux remain unproved.

`yoke self-host init` takes `--dir`, `--port`, and `--image` overrides. By
default it resolves the installed CLI's immutable release manifest and writes
that release's exact `<repository>:<sha12>` image to `.env`. The repository defaults
to `ghcr.io/upyoke/yoke-server`; set `settings.server_image_repository` in machine
config, or choose **Image repository** in the self-host onboarding preview, to
use a fork, mirror, or private registry. Enter a lowercase registry/repository
without a tag or digest; it must carry the same release commit tags.
Every fresh bundle therefore starts with matching CLI and server versions, and
a later container restart keeps the same server. `--image` remains an explicit
operator override. Generated credentials stay in host-owned files under `secrets/`
rather than `.env`, whose values Compose `$`-interpolates.

Refresh older bundles while preserving `.env` and database credentials:

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

Archives can contain raw capability secrets plus hashed credentials. Keep them owner-only and rotate secrets when custody changes. Restore revokes imported API tokens and browser sessions, grants neutral `admin` org-admin access, and mints one replacement token. Save its one-time success output, then run the printed `yoke self-host init --protect-existing --start` and `yoke connect` steps.

If the restore reported success but its one-time result was lost before you
could save it, mint a recovery credential while `core` remains stopped:

```bash
cd /path/to/yoke-server
yoke self-host import --dir . --recover-credential
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
Docker bypasses ufw/firewalld for published ports; bind to `127.0.0.1`
behind a TLS reverse proxy, or restrict access upstream. `yoke self-host init`
warns when the configured publish address is beyond loopback, including on
`--protect-existing --start`; the warning never blocks setup or startup.

## Engineer machines

Each engineer runs the installer, then connects to your server:

```bash
curl -fsSL https://upyoke.com/install | sh
yoke connect https://yoke.internal
yoke status
```

With company sign-in (OIDC) configured, the CLI displays a one-time code and
opens the server's workbench approval page. Sign in and approve **your own**
machine. The CLI polls and receives its machine-bound credential once; no
server operator needs to mint a token. The setup wizard's **A team server**
option discovers the same sign-in method after you enter the server URL.

Without company sign-in, connect with a pasted API token or token file:
`yoke connect https://yoke.internal --token-stdin`. The first-boot admin token
remains the bootstrap; an admin can mint other API tokens on the host with
`docker compose exec --user yoke core python3 -m yoke_core.domain.api_tokens_cli mint --actor <actor-id> --name <engineer-label>`.

Use HTTPS for network servers (numeric loopback HTTP is permitted locally).
The connection is saved only after `/v1/health` and `/v1/auth/identity` pass.
See [Machine authorization](public/reference/machine-authorization.md) for
expiry, retry, and single-use credential delivery.

## Workbench and browser sign-in

The server serves the workbench at its own URL. Run `yoke ui up` on a connected
CLI: company sign-in opens the server URL; without OIDC, your API token gets a
single-use sign-in link that expires in two minutes. Both give full read and
write as your actor. The walkthrough and same-origin cookie protection are in
[Browser Sign-In](self-host-browser-sign-in.md).

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
YOKE_GITHUB_APP_PRIVATE_KEY_FILE=/dev/shm/yoke-runtime-secrets/yoke-github-app-private-key

# Optional product-facing Connect GitHub profile; set all four or none.
YOKE_GITHUB_APP_WEB_URL=https://github.com
YOKE_GITHUB_APP_ID=<numeric-app-id>
YOKE_GITHUB_APP_CLIENT_ID=<public-client-id>
YOKE_GITHUB_APP_SLUG=<app-slug>
```

Enable the file binding in `.env`, then run `yoke self-host init --protect-existing --start`. The
GitHub App is disabled until all three values and the host key
are present. GitHub Enterprise Server uses its HTTPS API origin in
`YOKE_GITHUB_APP_API_URL`; redirects to another origin are rejected.
The key stays mode `0600` in the host bundle. The host command opens it and
streams it to the bootstrap alongside the database DSN and optional OIDC secret.
The runtime user writes mode `0600` copies in private tmpfs after the privilege
drop; host ownership and modes stay unchanged.

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
`/dev/shm/yoke-runtime-secrets/yoke-github-app-private-key`. Secret values never cross SSH and
are not placed in Compose environment variables, command arguments, Pulumi
state, or project-engine databases.

## Upgrades

Running bundles stay on their exact image pin until you deliberately advance
the pair. Upgrades use the configured image repository. From any directory, run:

```bash
yoke self-host upgrade --dir /path/to/yoke-server
```

The command performs a read-only preflight and shows the current image, target
release, exact target image, and ordered actions before asking you to type
`upgrade`. It then installs that release's CLI through the public installer
channel, atomically rewrites `YOKE_SERVER_IMAGE`, runs `docker compose pull
core`, refreshes the Compose template, and restarts through the private host handoff. Use `--yes` only when an automated run
has already accepted that same plan.

An active source-checkout CLI refuses this command before preview or install,
just as `yoke update` does. Update the checkout with git, then rebuild its
source server with `yoke core upgrade --from-checkout /path/to/yoke --build`.
Checkout builds pass Git HEAD and the checkout's setuptools-scm version into
the image, so installed wheels pass version and migration-readiness checks.
The refusal preserves the CLI install, bundle image pin, and running server.

Failures name the stage and exact retry. The pin is unchanged when CLI install
fails; after the CLI and pin advance, a pull or restart failure leaves both
durable identities on the target and prints the two Compose recovery commands.
On every boot the entrypoint converges additive schema before serving;
data-transforming changes still use Yoke's governed migration runner. Foreign
keys onto `environments.id` match its live type so a universe still on text
keys reaches the ordered history that converts them. The boot also declares a
bounded `idle_in_transaction_session_timeout` for its own session and records
it as the role's database default; a managed Postgres whose role cannot alter
its own defaults degrades with an `application_role_default_not_persisted`
line on stderr rather than refusing to serve. Confirm
the running source identity through the `build` field on `GET /v1/health`.

### Run a server from an edited Yoke checkout

Choosing **Edit Yoke source** in the wizard always activates that checkout for
the local CLI and harness. When the destination is guided self-hosting on the
same machine, the wizard also uses the existing local-core
`--from-checkout PATH --build` path so the private server image contains that
checkout's code. Connecting the edited client to an already-running team
server or upyoke.com does not replace its image; the remote server keeps its
deployed build.

The ordinary published-image bundle remains pinned to `YOKE_SERVER_IMAGE`.
Building a custom image from the repository Dockerfile and selecting that
private/local image is still supported, but editing a checkout does not
silently repoint an unrelated remote bundle.

## Take it back off

For full machine removal, use [`yoke uninstall`](public/install.md#uninstall). `yoke self-host teardown` removes the server install. It always stops and removes the
stack; everything further is opt-in and named for what it destroys:

```bash
cd yoke-server
yoke self-host teardown                       # stop the stack; keep the data
yoke self-host teardown --remove-images \
  --remove-bundle --destroy-universe          # remove everything, prompts first
```

Without `--destroy-universe` the `pgdata` volume survives, so
`yoke self-host init --protect-existing --start` brings the same universe back. With it, the volume and
every item, event, and credential in it are gone; the command asks for consent
unless you pass `--yes`. `--remove-images` removes the images this bundle uses
and reports any another container still needs. `--remove-bundle` deletes the
files Yoke wrote, `secrets/` and the admin token file included, and reports
anything else in the directory rather than deleting it.

Teardown atomically retires every machine connection pointing at this bundle's
server before stopping it, including each connection's unshared token file, so
no dead authority or credential is left behind. Pass `--keep-connection` to
leave all of them, or `--activate ENV` to name a connection for another server
that takes over as this machine's authority. Idle machine-config lock files
created by retirement are removed as part of teardown. Single-connection
retirement remains available on its own as
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
