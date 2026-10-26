# Golden baseline semantics and Yoke preparation

This is Yoke's project-owned manual baseline inventory and preparation policy.
Follow it with the existing ordered Machine QA procedures for
[macOS](../../packs/machine-qa/versions/1.3.48/files/docs/packs/machine-qa/macos-host-provisioning.md),
[Linux](../../packs/machine-qa/versions/1.3.48/files/docs/packs/machine-qa/linux-host-provisioning.md), or
[Windows/WSL2](../../packs/machine-qa/versions/1.3.48/files/docs/packs/machine-qa/windows-host-provisioning.md).
The [provisioning index](../../packs/machine-qa/versions/1.3.48/files/docs/packs/machine-qa/host-provisioning.md)
installs as `docs/packs/machine-qa/host-provisioning.md`. Complete its account,
network, tools, sign-in and GUI steps; add the runtime preparation below before
capture. Neither a package command nor a successful capture establishes readiness.

## Ownership and inventory

Preparation is manual, project-specific work with explicit host custody.
Generic Yoke/Machine QA registers, captures, restores and verifies declared
state; it does not install this project's baseline for other projects. Pack
recipes supply reusable OS steps, not a universal Docker or fixture policy.
Read registered settings and leases before acting; never operate a peer's host.
Substitute the dedicated account, private endpoint and approved paths from that
record. A fixture home must differ from ordinary worker and operator homes.

| Required Yoke state | Owner and proof |
| --- | --- |
| Private SSH access, dedicated non-root account, sufficient RAM/disk | OS procedure, registered secrets and actual exec |
| Declared desktop/session, input and capture permissions | OS procedure, bridge diagnosis and non-blank screenshot |
| Claude, Codex and Cursor vendor CLIs and live sign-ins | Supported vendor installs, versions and canonical tiny real requests |
| Claude bypass acceptance in dedicated fixture only | Canonical acceptance check; not authority for unrelated work |
| Mac saver Never, readable unlocked login Keychain, TCC grants | Canonical GUI checks plus effective bridge operation |
| Docker daemon, Compose v2, real Linux containers | Manual preparation and positive workload checks below |
| Mac runtime outside restored home, stable CLI/socket/context | External profile plus live-daemon/bind/reset proof below |
| Private-address Mac server when declared by a case | Host-address configuration and real companion/isolation proof |
| Browser application sign-in and separate browser identity store | Existing browser procedure and actual signed-in app page |

`fresh-host` keeps supported vendor tools/sign-ins and removes Yoke launchers
and state. `shell-preconfigured` adds the current Yoke shell launcher, installed
from the distribution of the environment the reset runs against (`--env prod`
installs the production release). A failed install records the tail of its
output as that operation's `reason` in the receipt. Neither means an empty OS. System packages, services, WSL registration and external VM
disks survive home restoration; declare and verify them separately. A running
container writing the restored home is a writer, not inert captured state.

Yoke uses Ubuntu 24.04 Linux (including arm64), Intel macOS Monterey and current
Apple Silicon macOS, and Windows Server with WSL2 Ubuntu 24.04. These are tested
fixture shapes, not support for every OS/version. Monterey supports remote-core
work only: packaged local PostgreSQL requires macOS 26 or newer; see
[operation constraints](test-machine-operations.md). Check each vendor's current
OS/architecture requirements before installing; version output alone is insufficient.
On older Macs use a runnable harness release as the OS guide describes, retaining
its actual version evidence. Windows runs Linux containers and CLIs in WSL, not
native Windows Yoke or Windows containers. Its real desktop proof remains required.

## Linux and Windows/WSL runtime

Complete the OS guide first, including private SSH, non-root account, permitted
sudo policy, supported harnesses/sign-ins, and xrdp/XFCE/input/browser tools where
declared. On Windows enable WSL2 and systemd for the registered Windows user's
default Ubuntu distribution, then use its dedicated Linux account. Cloud
instance-running is not readiness: wait for instance-status-ok and prove WSL
exec before starting its desktop. Virtualization must work, not merely be advertised.

For Ubuntu 24.04's distribution packages, run as the administrator in Linux/WSL:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker TESTUSER
```

Log the test account out/in so new group membership applies. Docker group access
is privileged; retain the fixture's approved access policy and Unix socket,
not an unauthenticated TCP daemon. As the test user prove `id`, `sudo -n true`,
`systemctl is-active docker`, `docker version` (client AND server) and
`docker compose version` (v2), then run the workloads below. Fix permission or
service failures before capture. Packages/services are outside the home golden.

Do not mix Ubuntu's `docker.io` packaging with Docker CE packages. An alternative
is Docker's [Ubuntu repository procedure](https://docs.docker.com/engine/install/ubuntu/)
and its [Compose plugin](https://docs.docker.com/compose/install/linux/): install
`docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`
after its repository/conflicting-package steps. Keep the chosen package family
and version evidence. Docker Desktop is not needed for the proved WSL Engine path.

## Manual Mac runtime preparation

Keep every OS-guide prerequisite: dedicated console account, private SSH,
Command Line Tools/Git, Python, GUI Terminal, privacy grants, harness sign-ins,
Claude acceptance, screen saver and Keychain. Do not replace these with Docker checks.
For a fresh install choose supported native binaries for `uname -m` and `sw_vers`.
The proved combination was Colima 0.10.3/Lima 2.2.1 with Docker CLI and Compose v2;
these are evidence versions, not mandatory patch pins for future machines.

Follow [Colima installation](https://colima.run/docs/installation/),
[Lima installation](https://lima-vm.io/docs/installation/),
[Docker static binaries](https://docs.docker.com/engine/install/binaries/), and
[Compose releases](https://github.com/docker/compose/releases).
On supported current macOS, `brew install colima docker docker-compose` is an
installation choice; follow the formula's plugin-discovery caveat. Check its OS
support first. The proved portable manual route installs release binaries:

| Host | Colima/Lima asset arch | Docker archive arch | Compose asset arch | VM |
| --- | --- | --- | --- | --- |
| Apple Silicon | arm64 | aarch64 | aarch64 | VZ on supported macOS |
| Intel | x86_64 | x86_64 | x86_64 | QEMU on Monterey |

Select reviewed release tags from each vendor and verify published checksums
before installation. Download Colima's `colima-Darwin-ARCH`, Lima's
`lima-VERSION-Darwin-ARCH.tar.gz`, Docker's `mac/static/stable/ARCH/docker-VERSION.tgz`,
and Compose's `docker-compose-darwin-ARCH` from those vendor pages. Preserve
existing binaries/configuration before replacing anything. Administrator installs
Colima and Docker executables mode 0755 in `/usr/local/bin`; extract Lima's full
`bin`, `share` and `libexec` distribution under `/usr/local`, preserving its
relative layout. Do not copy only `limactl`. Install the Compose executable mode
0755 as the test user's `~/.docker/cli-plugins/docker-compose`; this is captured
home state. Confirm native `colima version`, `limactl --version`, `docker --version`
and `docker compose version` in SSH and GUI Terminal. Reset must find Docker at
`/usr/local/bin/docker` or `/opt/homebrew/bin/docker`, not only a custom shell alias.

Monterey cannot use current Docker Desktop's supported OS range. The proved
Intel path uses [MacPorts](https://www.macports.org/install.php)' signed/notarized
installer for that exact OS, then `sudo port -N install qemu +target_x86_64`.
Put `/opt/local/bin` on the test user's PATH and prove `qemu-system-x86_64 --version`.
Use [Lima's QEMU requirements](https://lima-vm.io/docs/config/vmtype/qemu/).
Do not upgrade hardware/OS or accept a Desktop agreement as an implied repair.
Licensing, personal sign-in, password and 2FA gates go to the operator when needed.

### External profile, environment and first start

Choose a test-user-owned mode-0700 directory such as
`/Users/Shared/colima-TESTUSER`, outside the captured home AND every golden
retention parent. Administrator creates/chowns only that new directory; do not
change ownership of another user's state. In the account's captured `.zshenv`
(and any declared non-zsh launch environment) set the actual absolute paths:

```sh
export COLIMA_HOME=/Users/Shared/colima-TESTUSER
export LIMA_HOME="$COLIMA_HOME/_lima"
export COLIMA_CACHE_HOME="$COLIMA_HOME/cache"
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:$PATH"
```

Prove the same values in SSH and GUI Terminal. Quiesce the old runtime only with
custody and no foreign workload; preserve its stopped home-based tree outside
the home/retention parents. Create a clean vendor profile rather than moving
absolute-path VM metadata blindly. Never capture/copy a running VM disk into a
golden: reset can replace it while the hypervisor still writes it, corrupting
state and hiding the live daemon from ownership cleanup.

Start as the test user, never root. The proved first-start shape is:

```sh
colima start --runtime docker --cpus 2 --memory 4 --disk 20 --ssh-config=false
```

On supported Apple Silicon add `--vm-type vz`; the proved Monterey build chooses
QEMU and omits that unsupported flag. Preserve project-approved DNS/mount/resource
settings; the fixture used explicit `--dns` values, not universal DNS policy.
Require `colima status`, a responding Docker server and a context whose endpoint
is `unix://$COLIMA_HOME/default/docker.sock` (`docker context inspect colima`).
If needed create/select the context using `docker context create colima --docker
"host=unix://$COLIMA_HOME/default/docker.sock"` and `docker context use colima`;
inspect an existing context before changing it. Clear an unintended `DOCKER_HOST`
or `DOCKER_CONTEXT` override in the owned launch environment. Keep registry auth
and other Docker config keys. If an obsolete `credsStore=desktop` helper blocks
this runtime, back up private config and repair that diagnosed key only.

The live disk is under `$LIMA_HOME/_disks/colima/datadisk`; cache, VM metadata and
socket remain external, while context/plugin/env references restore with home.
A daemon failure requires the same environment and `colima start`, followed by
actual workloads, not a claim that the Docker executable proves readiness.
Sealed runtime extras must ensure the declared daemon is up and leave it running.

### A Mac serving its own LAN/Tailscale address

Loopback remains the default. A Linux VM IP is not the Mac's LAN/Tailscale IP.
For a declared numeric private-address server, use Colima's existing
[host-address option](https://github.com/abiosoft/colima/blob/v0.10.3/embedded/defaults/colima.yaml).
Read the installed `colima start --help`; the proved flag is
`--network-host-addresses=true`, with `--network-address=false`. With host custody,
no foreign workloads and a saved copy of the external `default/colima.yaml`:

```sh
colima stop
colima start --network-host-addresses=true --network-address=false
```

Compare parsed before/after config: only `network.hostAddresses` changes to true;
`network.address` stays false and all resource/runtime/mount/DNS settings stay.
`colima ssh -- ip -j address` must show the actual chosen Mac address replicated
on guest loopback. This does not authorize wildcard listeners, bridging, a proxy,
Tailscale rewrites or replacing the Mac server with Linux.

Use an unused private port and two uniquely named/labeled owned HTTP probe
containers. A tested image is Docker Official `busybox:1.37` with `/bin/busybox
httpd -f -p 8080 -h /tmp/www`; write a unique nonce to its `/tmp/www/index.html`.
Alpine's BusyBox build may lack `httpd`: first prove the app responds locally.
Publish the positive only with `-p MAC_PRIVATE_IP:PORT:8080`. From the companion
Mac require HTTP 200 and that nonce through MAC_PRIVATE_IP; the server's loopback
must not reach this private-only port. Independently publish the control only
with `-p 127.0.0.1:CONTROL_PORT:8080`; require local nonce success and failed
companion access through MAC_PRIVATE_IP. Inspect Docker PortBindings and native
listener addresses. No host mount is needed. Preserve command/output/config
hashes; remove only the exact owned labeled container IDs. A dead HTTP service
is not a passing isolation control. Repeat after both baselines and final reset.

For example, in the Mac server's native shell, substitute an approved address
and unused ports; choose unique names and keep returned IDs privately:

```sh
mac_ip=MAC_PRIVATE_IP
probe=baseline-http-UNIQUE
control=baseline-loopback-UNIQUE
nonce=baseline-nonce-UNIQUE
image=busybox:1.37
docker run -d --name "$probe" --label baseline.proof="$nonce" \
  -p "$mac_ip:55225:8080" "$image" /bin/sh -c \
  "mkdir -p /tmp/www; printf '%s' '$nonce' >/tmp/www/index.html; exec /bin/busybox httpd -f -p 8080 -h /tmp/www"
docker run -d --name "$control" --label baseline.proof="$nonce" \
  -p 127.0.0.1:55226:8080 "$image" /bin/sh -c \
  "mkdir -p /tmp/www; printf '%s' '$nonce' >/tmp/www/index.html; exec /bin/busybox httpd -f -p 8080 -h /tmp/www"
curl --fail --max-time 5 http://127.0.0.1:55226/
docker inspect --format '{{json .HostConfig.PortBindings}}' "$probe" "$control"
lsof -nP -iTCP:55225 -iTCP:55226 -sTCP:LISTEN
```

From the companion require `curl --fail --max-time 5 http://MAC_PRIVATE_IP:55225/`
to return the nonce and status 200; port 55226 must fail from that same companion.
On the server port 55225 must fail through 127.0.0.1. Retry only application
startup until the local control responds; preserve failures. Inspect labels and
remove the two exact recorded IDs with `docker rm -f ID ID`, never a broad prune.

## Runtime probes, capture and reset proof

As the fixture user in each declared execution context, require server output,
Compose v2, zero exits and expected markers from real workloads:

```sh
docker version
docker compose version
docker run --rm --network none alpine:3.22 /bin/echo docker-container-ok
docker compose -p baseline-runtime-check -f - run --rm check <<'YAML'
services:
  check:
    image: alpine:3.22
    network_mode: none
    command: [/bin/echo, compose-container-ok]
YAML
```

Use a unique project name when another check might run. Remove that project's
containers/networks/images through its owned cleanup, leaving unrelated images,
volumes and workloads alone. Record native exits and output, not CLI presence.
For restored-home proof, capture a harmless unique-token file in the home, then
run a container with `--mount type=bind,src=ABSOLUTE_RESTORED_FILE,dst=/proof,readonly`
and require the token read from `/proof` after each restore. No credential file
or whole-home mount belongs in a probe. Remove only the owned temporary evidence.

Prepare custom probes by retaining EVERY canonical standard name from the OS
procedure and adding real runtime/Compose/bind assertions with absolute argv
and positive expected output. Capture replaces standard programs with canonical
ones and seals extras; it never imports an older sidecar implicitly. Mac's six
standards include real requests, bypass, saver and GUI Keychain; Linux's five
include desktop input; Windows/WSL's four do not establish desktop rendering.
Preserve standard checks and credential/GUI acceptance, even when Docker passes.
Keep private probe programs, raw reports, manifests and archives out of Git.

Before every capture ATTEMPT, choose a distinct new destination PARENT outside
the home, e.g. `/Users/Shared/yoke-golden-attempt-DATE-UNIQUE/home` or
`/var/lib/yoke-golden-attempt-DATE-UNIQUE/home`. Check space and record every
project's current golden and sidecars (`.manifest`, `.probes`, `.harness-clis`).
Capture retention keeps every golden any project registered for the same host
and user, and anything newer than the new golden; it deletes older unregistered
siblings, including failed attempts. A new basename does not preserve them. Never
approve deletion merely to retry; preserve existing paths/evidence and use a
separate parent, including on failure. An already lost snapshot is not preserved.

Read served command help, then use the registered capture with the complete
`--probes-file`, followed by verify and a final fresh-host reset under custody:

```text
yoke test-machine golden-capture --project P --test-machine NAME --destination NEW_PARENT/home --probes-file PRIVATE_PROBES_FILE
yoke test-machine verify --project P --test-machine NAME
yoke test-machine reset --project P --test-machine NAME --baseline fresh-host
yoke test-machine get --project P --test-machine NAME
```

These are destructive operations, requiring separate provisioning authority.
For EACH restore (`fresh-host`, `shell-preconfigured`, final `fresh-host`), have
the daemon responding BEFORE reset and seed only recorded, project-owned canary
container/volume/image IDs under the product's `com.docker.compose.project=yoke-server`
ownership label, with no foreign workload or home writer. Preserve the IDs in
external private evidence. Require the receipt's removal evidence and live
daemon queries proving those exact IDs absent, then real Docker/Compose and
restored readonly-bind proof. An unreachable daemon cannot prove cleanup.
Verify ends shell-preconfigured; final reset must prove Yoke launcher absent.
On a private-address Mac repeat config/guest address/companion/loopback controls
after each reset. Remove final owned canaries/probes and leave the external
runtime running. Do not recapture for an external-only profile change.

## Evidence limits and recovery

On 2026-10-22 Ubuntu passed capture, both baselines and final fresh-host with
all canonical and Docker/Compose probes. Both Intel and Apple Silicon Macs
passed the external-runtime roundtrip, actual labeled cleanup and restored
readonly bind; their daemons stayed running. Apple Silicon's private-address
HTTP and loopback controls also passed after fresh-host, shell-preconfigured
and final fresh-host, preserving the sealed golden and probes unchanged.
Windows/WSL passed real Docker/Compose, capture and both home restores, but
verify failed `screenshot_png_invalid` (blank XFCE/xrdp desktop). It is NOT fully
ready; successful desktop verification and final fresh-host proof remain owed.
A later live read found no window-manager/compositor owner, so old compositor
warnings do not establish the cause. Repair the selected desktop startup under
separate authority; preserve screenshot validation, goldens and failure evidence.

Capture is a private archive/manifest/probe seal, not live sign-in or desktop
proof. SSH access, TCC, live harness logins/Keychain and browser identities are
preserved rather than restored from stale credentials; consult the OS procedure
for its exact exclusions. Never export credentials to bypass a GUI boundary.
Mac capture omits sockets/FIFOs and preserves ACLs/xattrs; unexpected foreign
owners still refuse. A partial home restore is never a new baseline.

A refusal's named phase, reason and recovery own the next step. Preserve failed
receipts and copies. Quota means wait for capacity; transport means repair the
route/service; only diagnosed authentication calls for sign-in. Never reset
credentials for an unknown exit. `test_machine_sign_in_app_quit_not_proved`
requires quitting the named app through its UI before copying; never force past
it. `golden_capture_copy_home_failed` retains `copy_stderr`; repair its cause
and choose a new parent. `golden_snapshot_retention_failed` can follow successful
registration: read removed/kept paths before any further capture. Verify's
`registered_golden_missing` names each project whose registered golden is gone:
capture a new golden for it. Never delete or move a registered golden by hand. A failed
reset retains `reset_phase`, process state and `failed_calls` where available;
missing stdout proves no cause. Fix the named writer/permission/transport and
retry the sealed restore; never weaken a probe or edit a seal to make it pass.

[Operation contracts](test-machine-operations.md) own leases and receipts.
For hosted approval, the production installer campaign uses `https://app.upyoke.com`;
no installed machine case requires Stage sign-in. The existing OS browser
procedure owns live signed-in application proof and password/2FA handoff;
actual candidate UI and terminal completion remain separate evidence.
