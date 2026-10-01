# Maintaining a private fork

Yoke tolerates an operator-maintained fork: you supply the installer,
release artifacts, wheel index, and server image. Installers and relays can
stay bound to that distribution. You own building, publishing, testing,
and updating it; upstream's hosted release service does not publish your fork.

## Bind the first download

Serve the fork's installer shim at your distribution's `/install` endpoint.
Download that shim from your own host and set the same distribution origin
for its Python helper and wheels:

```bash
curl -fsSL https://packages.example.com/install -o /tmp/yoke-fork-install
YOKE_INSTALL_BASE_URL=https://packages.example.com \
  sh /tmp/yoke-fork-install --channel private
```

Replace the example host and channel with your own. Setting the origin only
after downloading the upstream installer does not bind the first download
to your fork. The origin is a credential-free HTTP(S) origin, without a
path, query, fragment, or embedded username/password. It names the package
host, which can differ from your control-plane API host.

After installation, open a new terminal and run `yoke status`. The installer
records `settings.distribution.origin` and `.channel` in `~/.yoke/config.json`.
Later `yoke update` reads that record in a fresh shell; no persistent shell
export is needed. `yoke update --channel NAME` selects another channel at
the recorded origin and saves it after a successful update.

For an install missing the record, explicitly select your distribution:

```bash
yoke config distribution set --origin https://packages.example.com --channel private
```

Run the command's `--help` for its flags. This selection changes the install
distribution, not your active control-plane connection.

## Supply artifacts and a wheel index

The distribution host must serve the fork's `dist/install.py`, channel
document at `dist/channels/CHANNEL.json`, release metadata under
`dist/releases/VERSION/`, and a Python simple index at `/simple/`. Supply
the split product wheels with one matching version (`yoke-cli`,
`yoke-contracts`, `yoke-core`, and `yoke-harness`) and their dependencies.
The installer and updater consume these existing formats; a bare directory
of wheels alone is not an update channel. Channel documents used by
`yoke update` carry schema version 3, the channel and version, an
`installer.python_url` equal to `ORIGIN/dist/install.py`, and migration
history evidence with the source commit and manifest digest/URLs. Keep
the artifacts immutable and verify them through your own publishing process.

A private relay installs the exact immutable version reported by its server
handshake, using `RECORDED_ORIGIN/simple/`. Publish that version before
booting the server that advertises it; it must include a PEP 440 local
release segment. The relay does not use the channel to choose a different
version, derive an index from the API URL, or substitute upstream's Yoke
index. Public dependencies still resolve from PyPI. Hosted upstream stage
and production connections use their respective hosted indexes.

Configure the server connection through [Onboard](install.md), then run:

```bash
yoke --env team relay install
yoke --env team relay status
```

Use your configured environment in place of `team`. For a private host with
no valid distribution record, relay installation refuses with
`relay_release_fetch_failed` and a `distribution_origin_missing` or other
distribution validation reason. The refusal records recovery instructions
in relay status and preserves any prior release. Repair the record with
`yoke config distribution set`, then retry the named relay install command.

## Build and boot your server

Docker must be available. The local core launcher can build directly from
your fork checkout and start that image:

```bash
yoke core start --from-checkout /path/to/yoke-fork --build
yoke core status
```

After updating the checkout, rebuild with
`yoke core upgrade --from-checkout /path/to/yoke-fork --build`.
Run each command's `--help` for ports and other options. For a separately
published image, use `yoke core start --image IMAGE` or initialize a team
server bundle with `yoke self-host init --dir /path/to/server --image IMAGE`.
Supply your fork's exact immutable image reference; explicitly selecting
an image avoids selecting an upstream image from release metadata. Follow
[Self-hosted mode](modes.md) for starting the bundle, connecting, and TLS.
Your image, client wheels, and handshake version must describe the same build.

`yoke update` and `yoke self-host upgrade` protect an active source-checkout
install: they refuse to replace it with packaged releases. Update source
with git, then rebuild the server from that checkout. A source-only server
does not by itself supply the versioned wheels a release-following relay
needs; publish matching artifacts before using that relay path.

## Unsupported at this level

- Publishing a private fork through upstream workflows or upstream attestations.
- Automatically accepting schema-changing upstream merges. You own assessing
  migrations, rehearsing them against your universes, and maintaining history.
- Downstream version ordering or channel arbitration between upstream and a fork.
- Fork-owned item gates or a fork-specific release-governance system.

These are outside the tolerated-fork contract. Keep your publishing and
upgrade policy operator-owned; no automatic fork governance is provided.
