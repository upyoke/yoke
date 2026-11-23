# Self-Host Yoke

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Install and run a server
<!-- /yoke:breadcrumbs -->

Run the Yoke API server on your own host: one `docker compose` bundle carrying
the published server image plus a Postgres 17 database. Your data stays on
hardware you control; engineers point their CLIs at your server instead of the
hosted platform.

Windows hosting requires WSL2 Ubuntu with Yoke and Docker Compose inside.
Native hosting refuses before writes. Same-PC `localhost` forwarding is
expected, unverified. See [Windows hosting](../start/windows-wsl.md).

## Quickstart

Install [Docker with Compose](https://docs.docker.com/get-started/get-docker/)
on the server host first, then verify `docker compose version` succeeds.
Docker Desktop includes Compose; Docker Engine installations need the Compose
plugin. Init checks this prerequisite before writing or changing the bundle.
If Docker or Compose is missing, install Docker (with Compose) and run
`yoke self-host init` again; Yoke does not install them for you.
On the server host:

```bash
# 1. Install the CLI (also how engineer machines install it later).
curl -fsSL https://upyoke.com/install | sh

# 2. Materialize the compose bundle. Writes docker-compose.yml, .env
#    (carrying your name: first boot creates the first admin as you),
#    and generated database credentials as owner-only secret files —
#    the generated password is never printed. A marked block in
#    .gitignore protects .env and secrets/ without replacing your rules.
yoke self-host init --admin-name "Your Name" --start
cd "${YOKE_MACHINE_HOME:-$HOME/.yoke}/yoke-server"

# 3. First boot writes the reusable administrator token to an owner-only
#    file. The log names the path and never carries the token itself.
docker compose logs core

# 4. Attach your CLI (verifies the server and token before persisting
#    anything). Keep the owner-only token file: it stays valid until you
#    revoke it, and rerunning `yoke setup` on this host reconnects with it.
yoke connect http://127.0.0.1:8765 --token-stdin < secrets/first-boot-admin-token

# 5. Confirm the machine is wired up. This fails if the server is not
#    answering, so a green run means the whole path works.
yoke status
```

`yoke connect` with a first-boot token registers the machine on that server and
stores a credential bound to this machine before installing or reusing the
destination relay. With `--no-activate`, the active connection stays selected.
Inspect the authenticated heartbeat with `yoke --env NAME relay status`.
If registration or relay setup fails, the connection remains saved and the
command reports how to recover.

The host command opens each mode `0600` input as its non-root operator and streams it on stdin through Docker exec. The container drops to its runtime user and writes private tmpfs copies; no host file is mounted or chowned and no credential is placed in an environment variable. The admin token returns over that same private handoff, outside Docker logs; the host atomically writes its owner-only token file and acknowledges durable storage before token creation commits. A failed handoff refuses with a reason and retry command.
Start/restart an existing bundle with `yoke self-host init --dir PATH --protect-existing --start`. This refreshes the packaged Compose template, preserving `.env`, database credentials, and the Postgres volume. Keep runtime settings in `.env`; reapply any custom Compose changes after a template refresh. Automatic container restart is disabled: after a host/daemon restart, run that host command again so it can reopen the protected inputs. Raw Compose starts alone cannot supply the handoff. Native Ubuntu rootful Docker is exercised by the manual bootstrap probe; rootless Docker and Fedora/SELinux remain unproved.
A new bundle requires `--admin-name`, written to `.env` as `YOKE_ADMIN_NAME`; first boot refuses to birth a universe without it and names the fix (set it in `.env`, then restart). The bundle defaults to `~/.yoke/yoke-server` (`YOKE_MACHINE_HOME/yoke-server` when set), outside projects. `yoke self-host init` takes `--dir`, `--port`, and `--image` overrides. By default it resolves the installed CLI's immutable release manifest and writes that release's exact `<repository>:<BASE.YYYYMMDDHHMM>` image to `.env`. The repository defaults to `ghcr.io/upyoke/yoke-server`; set `settings.server_image_repository` in machine config, or choose **Image repository** in the self-host onboarding preview, to use a fork, mirror, or private registry. Enter a lowercase registry/repository without a tag or digest; it must carry the same immutable release version tags. Every fresh bundle therefore starts with matching CLI and server versions, and a later container restart keeps the same server. `--image` remains an explicit operator override. Generated credentials stay in host-owned files under `secrets/` rather than `.env`, whose values Compose `$`-interpolates.
Refresh older bundles while preserving `.env` and database credentials:

```bash
yoke self-host init --dir /path/to/yoke-server --protect-existing
```

The command preserves operator-authored `.gitignore` rules and reports that credentials were not regenerated. The bundle and `secrets/` must be real operator-owned directories; `secrets/` must be mode `0700`. It refuses symlinked paths and secrets already tracked by Git. Remove reported paths from the index, rotate any exposed credential, and retry.

## Mac runtime and private-address preparation

On supported macOS choose [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/)
or [Colima with Docker CLI and Compose](https://colima.run/docs/installation/).
Check vendor OS/architecture support; current Desktop does not support older
macOS such as Monterey. Follow Colima/Lima's QEMU instructions for those hosts.
Install Compose as a Docker CLI plugin; `docker compose version` must report v2.
Start your chosen runtime yourself: open Desktop and finish its approved first
run, or run `colima start` in the owning user's Colima environment/context.
Require `docker info` to succeed before Start; Yoke installs or starts no runtime.
Setup's interactive and agent modes share this check and explain what to repair.
Loopback hosting needs no Colima host-address change. For a numeric Mac LAN or
Tailscale `--listen` address, Colima must forward that HOST address into its VM.
Read the installed `colima start --help` and [vendor hostAddresses configuration](https://github.com/abiosoft/colima/blob/v0.10.3/embedded/defaults/colima.yaml).
With permission to stop that runtime, save its profile and ensure no unrelated
workload is running, then run `colima stop` followed by
`colima start --network-host-addresses=true --network-address=false`.
Preserve every other profile setting. The VM address is not the Mac address.
Verify a container published only on the chosen Mac private IP from another
machine; separately require a loopback-only control to remain unreachable there.
An unsupported flag or failed bind needs runtime configuration repair before
retrying the existing bundle with `--protect-existing --start`; widening to
`0.0.0.0` is not the repair. These Colima settings do not apply to Docker Desktop.

## Move an existing universe here

Point the import at a fresh or replaceable bundle, keep `core` stopped, and protect the archive as private control-plane data:

```bash
yoke self-host init --dir /path/to/yoke-server
chmod 600 ~/Downloads/acme-universe-20260714T120000Z.tar
yoke self-host import ~/Downloads/acme-universe-20260714T120000Z.tar \
  --dir /path/to/yoke-server
```

The tar carries the database dump and freeze receipt (see [Universe portability](../guide/universe-portability.md)); that receipt supplies checksum verification. Type `replace` at the prompt, or pass `--yes` for a non-interactive replacement.
The command requires Docker with Compose, validates the bundle, and refuses while `core` runs. The archive must be a current-owner, single-link regular file with no group/world access. Compose starts only the database and streams the archive to a one-off process in the pinned image; it never bind-mounts the host archive.
Uploaded DDL never runs. Yoke creates the trusted destination schema, validates the bounded archive, and restores approved data and sequences in one transaction; retry replaces a failed or interrupted attempt.
Archives contain private records and hashed credentials; capability-secret data is excluded. Keep them owner-only and rotate secrets when custody changes. Restore revokes imported API tokens and browser sessions, re-credentials the archive's org-admin person (an archive with none refuses), and mints one replacement token. Save its one-time success output, then run the printed `yoke self-host init --protect-existing --start` and `yoke connect` steps.
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
## Networking

By default the API publishes on loopback only (`127.0.0.1:8765`). To
serve your network, pass `--listen ADDRESS` at init, for example
`yoke self-host init --admin-name "Your Name" --listen 100.101.102.103 --start`.
This writes `YOKE_API_PUBLISH=100.101.102.103:8765` in `.env`; teammates run
`yoke connect http://100.101.102.103:8765`. Use a LAN or Tailscale IP;
`--listen 0.0.0.0` binds all IPv4 interfaces, so teammates substitute the
server's reachable private IP. IPv6 binds are supported too.
Private HTTP permits 10/8, 172.16/12, 192.168/16, 100.64/10, fd00::/8 and
`*.ts.net`; public HTTP is refused with HTTPS recovery. Each connect warns
that the machine token travels unencrypted: safe on Tailscale or a VPN;
use TLS on a shared LAN. Existing bundles keep their `.env` with
`--protect-existing`; edit `YOKE_API_PUBLISH` there and restart to change it.
Docker bypasses ufw/firewalld for published ports; bind to `127.0.0.1`
behind a TLS reverse proxy, or restrict access upstream. `yoke self-host init`
warns when the configured publish address is beyond loopback, including on
`--protect-existing --start`; the warning never blocks setup or startup.
Set `YOKE_API_TRUSTED_PROXIES` in `.env` to the proxy IPs/CIDRs seen by core;
restart with `yoke self-host init --dir PATH --protect-existing --start`.
See [proxy forwarding](browser-sign-in.md#proxy-forwarding) for headers and trust.

## Engineer machines

See [People and machines](people.md) to connect engineers and approve your own machines.

## Restore admin access

See [Restore admin access](people.md#restore-admin-access) to reconnect the host
or mint a recovery credential without replacing the server.

## Web dashboard and browser sign-in

See [Browser sign-in](browser-sign-in.md) for token links, company sign-in and proxy configuration.

## GitHub App server automation

Use a dedicated operator-owned App for server automation. [GitHub App setup](github-app.md) covers private-key ingress and runtime settings.

## Upgrades

Upgrade the pinned pair using the configured image repository:

```bash
yoke self-host upgrade --dir /path/to/yoke-server
```

If the image pin and CLI already match the release, it reports already current
and changes nothing. Otherwise preflight shows images, release, origin and
actions, then asks you to type `upgrade`. It installs the paired CLI, atomically
updates `YOKE_SERVER_IMAGE`, pulls `core`, refreshes Compose, and restarts
through the private host handoff. When only the CLI is behind, the plan is one
step: it installs the CLI and leaves the running server untouched. `--yes`
accepts this plan automatically.

Setup and upgrade use `settings.distribution.origin`, ignoring
`YOKE_INSTALL_BASE_URL`. Upgrade defaults to `settings.distribution.channel`;
`--channel` overrides only the channel. Missing or invalid metadata refuses before
fetching; repair with `yoke settings set distribution '{"origin":"URL","channel":"NAME"}'`.
Setup `--image` skips resolution.

Source-checkout CLIs refuse upgrades; update with git and rebuild with
`yoke core upgrade --from-checkout /path/to/yoke --build`.
Checkout images carry Git HEAD and setuptools-scm version for readiness checks.
Failures name the stage and exact retry. If the CLI installer fails, the upgrade
reports the active launcher's version or says it is unknown. It leaves the
bundle pin and server untouched. After the CLI and pin advance, a pull or
restart failure leaves both durable identities on the target and prints the
two Compose recovery commands.
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

`yoke self-host teardown` removes the self-host stack and its machine-side
installation. Run it from anywhere. It defaults to the machine-home bundle.
Name another bundle with `--dir PATH`:

```bash
yoke self-host teardown                       # remove the stack, keep its data
yoke self-host teardown --remove-images \
  --remove-bundle --destroy-universe          # also remove bundle, images, and data
```

Teardown finds every machine connection that reaches the bundle, using its
published URL or verifying a proxy connection's token against the local
server. It checks every checkout registered to those connections first. A
refusal, such as a dirty lane, stops teardown before it changes anything.
Teardown then uninstalls the connections' relays and project layers before it
retires their connections and unshared token files and stops Compose. If
cleanup fails, repair the named step and retry while the server and connection
are still available. A connection that cannot be verified is listed under
`connection left` with its removal command.

`--activate ENV` selects the connection to use when retiring the active one.
Any remaining universe connection, including an embedded local universe,
keeps the CLI installed. When the last connection goes away, teardown runs
the full [machine uninstall](../start/uninstall.md#uninstall), including
machine-wide hooks and CLI removal. Self-host init requires the CLI to be
installed first. `--keep-connection` skips all machine-side removal.

The `pgdata` volume survives by default. With the bundle and CLI available,
`yoke self-host init --protect-existing --start` brings back the same universe.
`--destroy-universe` deletes the database volume and prompts for consent unless
you pass `--yes`. `--remove-images` removes the images this bundle uses and
reports any still in use. `--remove-bundle` deletes the files Yoke wrote,
including the bundle's secrets and admin token, and keeps other files. After a
full machine uninstall, it also removes any folders the bundle leaves empty, up
to and including the machine home.

## You own the operations

- **Uptime is yours.** Automatic restart is disabled. After a failure or host
  restart, use `yoke self-host init --dir PATH --protect-existing --start`
  to reopen the private inputs. You own monitoring and capacity.
- **Backups are yours.** All state lives in the `pgdata` volume; use
  `yoke universe export` for portable archives and retain regular Postgres or
  volume snapshots for infrastructure-level recovery before upgrades and on a
  schedule.
- **TLS is yours.** Use TLS for public access or shared LANs and declare proxy peers
  in `YOKE_API_TRUSTED_PROXIES`; publish the API only where intended.


### Optional GeoIP context

Mount unpacked DB-IP Lite City and ASN `.mmdb` files read-only and set
`YOKE_GEOIP_CITY_DB` and `YOKE_GEOIP_ASN_DB` to their container paths.
Update the files monthly; missing files leave collection working without geo
fields. The trusted client IP is still stored. Follow the privacy and
[DB-IP credit requirements](../operations/events.md#browser-and-network-context).
