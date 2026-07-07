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
**not** hosted by Yoke; they resolve from PyPI via an extra index URL.

## Install Command

```bash
uv tool install yoke-cli --with yoke-harness --with yoke-core \
  --index-url https://api.upyoke.com/simple/ \
  --extra-index-url https://pypi.org/simple/
```

`--index-url` points at Yoke's PEP 503 index (the product wheels);
`--extra-index-url` lets uv resolve every third-party dependency from PyPI. Each
product wheel link carries a `#sha256=<hex>` fragment so uv verifies wheel
integrity on download.

## Build Release Artifacts

From a Yoke source checkout, build the public release artifact tree with the
same entrypoint CI uses:

```bash
uv run python -m yoke_core.tools.build_release \
  --repo-root . \
  --output-root /tmp/yoke-release \
  --base-url https://api.upyoke.com \
  --channel latest
```

The builder creates the product wheels, the PEP 503 `simple/` index, the
per-wheel `release-records.json`, the channel JSON, `dist/install.py`, and the
root `/install` shim. Installer consumers do not need a Yoke source checkout;
they install from the hosted index.

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
```

Wheels under `dist/releases/<version>/` are immutable (one-year `immutable`
cache); their bytes are never overwritten. The `simple/` index pages are
short-cache mutable and CloudFront-invalidated on every publish, because they
accrete new wheels as versions ship.

## Channel Pointer

Each channel pointer at `/dist/channels/<channel>.json` maps a channel to one
immutable version pin. Its shape is defined in
[`channel-pointer.schema.json`](channel-pointer.schema.json):

```json
{
  "schema_version": 2,
  "channel": "stable",
  "version": "<version>",
  "generated_at": "<commit ISO time>",
  "index_url": "https://api.upyoke.com/simple/",
  "release_base_url": "https://api.upyoke.com/dist/releases/<version>",
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

The `yoke-distribution-publish` workflow uploads immutable wheels and the
versioned `release-records.json` first (refusing any overwrite whose bytes
differ), uploads the mutable `simple/` index pages, channel JSON, and installer
assets, invalidates the mutable CloudFront paths (`/simple/*`, `/install`,
`/dist/install.py`, `/dist/channels/*.json`), then re-checks public reachability
and cache headers through `yoke_core.tools.distribution_publish`. It does not
delete `dist/releases/<version>` objects; rolling cleanup must be an explicit
retention rule that leaves retained releases installable.
