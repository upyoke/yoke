# Yoke Distribution Contract

This directory defines the contract for the installable Yoke product client.
Yoke hosts a private PEP 503 "simple" index that lists only the Yoke product
wheels:

- `yoke-contracts`
- `yoke-cli`
- `yoke-harness`
- `yoke-core`

Every machine carries the engine (`yoke-core`); safety comes from the DSN
authority boundary, not from keeping engine code off machines. Third-party
dependencies (pydantic, textual, pyfiglet, and their transitive closure) are
**not** hosted by Yoke; they resolve from an explicitly selected public PyPI
default while the Yoke index remains the resolver's first index.

## Install Command

```bash
curl -fsSL https://upyoke.com/install | sh
```

The public installer resolves the channel once, pins all four Yoke product
packages to that version, and gives uv a generated private-index configuration.
It also pins public PyPI as the dependency default and clears ambient uv index
settings for that resolver run. Direct multi-index `uv tool install` commands
are not a supported install surface: their index precedence can select a public
namesake before the Yoke package index. Each product wheel link carries a
`#sha256=<hex>` fragment so uv verifies wheel integrity on download.

## Build Release Artifacts

From a Yoke source checkout, build the public release artifact tree with the
same entrypoint CI uses:

```bash
uv run python -m yoke_core.tools.build_release \
  --repo-root . \
  --output-root /tmp/yoke-release \
  --base-url https://api.upyoke.com \
  --source-commit <full-source-commit> \
  --channel latest
```

The builder creates the product wheels, the PEP 503 `simple/` index, the
per-wheel `release-records.json`, deterministic migration manifest,
independently attestable migration evidence record, channel JSON,
`dist/install.py`, and the root `/install` shim. Installer consumers do not
need a Yoke source checkout; they install from the hosted index.

## Public Release Layout

The PEP 503 index is served at `<base>/simple/` and is the value of `index_url`
the installer passes to uv. Its per-project pages link to immutable versioned
wheels, so a single `simple/` tree spans every retained version.

```text
https://api.upyoke.com/simple/                       PEP 503 root (lists the product projects)
https://api.upyoke.com/simple/yoke-cli/            per-project wheel links (#sha256=)
https://api.upyoke.com/simple/yoke-contracts/
https://api.upyoke.com/simple/yoke-harness/
https://api.upyoke.com/simple/yoke-core/
https://api.upyoke.com/dist/releases/<version>/wheels/<wheel>.whl   immutable
https://api.upyoke.com/dist/releases/<version>/release-records.json immutable
https://api.upyoke.com/dist/releases/<version>/migration-history.json immutable
https://api.upyoke.com/dist/releases/<version>/migration-history-record.json immutable
```

Wheels under `dist/releases/<version>/` are immutable (one-year `immutable`
cache); their bytes are never overwritten. The `simple/` index pages are
short-cache mutable and CloudFront-invalidated on every publish, because they
accrete new wheels as versions ship.

## Channel Pointer

Each channel pointer at `/dist/channels/<channel>.json` maps a channel to one
immutable version pin. Historical schema v2 pointers remain valid without
migration evidence; content-aware releases publish schema v3 and fail closed
without it. The shapes are defined in
[`channel-pointer.schema.json`](channel-pointer.schema.json):

```json
{
  "schema_version": 3,
  "channel": "stable",
  "version": "<version>",
  "generated_at": "<commit ISO time>",
  "index_url": "https://api.upyoke.com/simple/",
  "release_base_url": "https://api.upyoke.com/dist/releases/<version>",
  "migration_history": {
    "manifest_url": "https://api.upyoke.com/dist/releases/<version>/migration-history.json",
    "evidence_url": "https://api.upyoke.com/dist/releases/<version>/migration-history-record.json",
    "manifest_sha256": "<sha256>",
    "source_commit": "<full-source-commit>"
  },
  "installer": {
    "python_url": "https://api.upyoke.com/dist/install.py",
    "shell_url": "https://api.upyoke.com/install"
  }
}
```

Mutable entrypoints stay short cached and are invalidated after publish:

```text
https://api.upyoke.com/install
https://api.upyoke.com/dist/install.py
https://api.upyoke.com/dist/channels/stable.json
https://api.upyoke.com/simple/
```

## Publish Flow

The release factory validates and attests the wheels, migration manifest, and
migration evidence record against one full source commit. Release validation
rejects any manifest/record/wheel mismatch; channel generation repeats the
externally usable manifest digest and source commit. The
`yoke-distribution-publish` workflow uploads those immutable files and the
versioned `release-records.json` first (refusing any overwrite whose bytes
differ), uploads the mutable `simple/` index pages, channel JSON, and installer
assets, invalidates the mutable CloudFront paths (`/simple/*`, `/install`,
`/dist/install.py`, `/dist/channels/*.json`), then re-checks public reachability
and cache headers through `yoke_core.tools.distribution_publish`. It does not
delete `dist/releases/<version>` objects; rolling cleanup must be an explicit
retention rule that leaves retained releases installable.
