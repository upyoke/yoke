# Contributing to Yoke

Yoke is [Fair Source](https://fair.io): you can read, audit, fork and
contribute to the source. This page owns contributor setup; product users
start with [installation](docs/public/start/install.md).

Cloning activates nothing. The installed `yoke` continues to use its packaged
wheels until you explicitly bind a source checkout.

## Fork and test without Yoke

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Git,
and Node.js 22 with npm. Database tests need PostgreSQL server tools
(`initdb`, `pg_ctl`, `pg_isready`) on PATH; use a normal user, not root.
The tests create disposable databases, so do not point them at real data.
Configure a Git name and email for tests that create commits.

Fork on GitHub if you want to submit changes, then clone your fork over HTTPS
(replace `YOUR-ACCOUNT` below; use `upyoke` to read the original):

```bash
git clone https://github.com/YOUR-ACCOUNT/yoke.git
cd yoke
uv sync --all-packages --all-groups --locked
npm ci --prefix packages/yoke-core/src/yoke_core/ui
uv run --frozen python3 -m pytest runtime/api runtime/harness tests -n auto
uv run --frozen python3 -m ruff check PATH_TO_CHANGED_PYTHON_FILE
```

Direct pytest needs no installed Yoke, account, project registration or work
claim. For a focused check, replace the three test roots with specific test
paths; use `-n 0` for order-sensitive debugging. The full suite is large.
The generic `yoke_core.tools.run_tests` wrapper and `yoke watch pytest`
resolve Yoke project authority, so use direct pytest for an unregistered fork.
Ruff is pinned in the locked development environment; pass each changed Python
file to match CI's changed-file lint scope.

## Develop inside Yoke

Install the [packaged product](docs/public/start/install.md), register/install
this checkout as a project through setup, and claim an item before preparing
its lane. Read [AGENTS.md](AGENTS.md) and the
[source-dev doctrine](docs/source-dev-doctrine.md).

```bash
yoke dev setup /absolute/path/to/yoke --editable-install --yes
yoke status
yoke watch pytest --impacted main --bounded
yoke dev ruff-changed --base main
```

`yoke dev setup` owns source-link repair, editable installation and optional
local PostgreSQL admin setup (`--with-test-postgres`, `--set-active-env`, and
the tunnel/authority flags in `yoke dev setup --help`). The `install:` line of
`yoke status` says `packaged wheel <version>` or `source checkout <path>`.
The editable shim reads the checkout path from machine config, so update
that path after moving the checkout; a bare `pip install -e` needs reinstalling.

Use `yoke dev run -- <command>` for lane source commands: it binds the claimed
lane and locked environment, and isolates machine administration context.
Commit before CI; the impacted watcher runs remotely for this project.
The attached QA case owns the full suite. Add `--format-check` to
`yoke dev ruff-changed` when checking formatting too.

Editable installation replaces the packaged wheels. Finish running Yoke
commands before repointing the launcher; setup defers this replacement until
its last step. To return to the packaged product, rerun the public installer.
To update a bound source checkout, update Git rather than using `yoke update`.

Run `yoke dev yokepedia` to browse the local map of rules, skills, roles and
teaching surfaces.

### Preview an unshipped project layer

Source maintainers can preview a local checkout's skills, agents, rules and
docs without changing the target or its machine configuration:

```bash
yoke project refresh /absolute/path/to/project \
  --source-checkout /absolute/path/to/yoke \
  --project-id PROJECT_ID --project-slug PROJECT_SLUG --json
```

After reviewing it, repeat with `--apply`. For a linked worktree lacking its
ignored manifest, also pass `--manifest-from /absolute/path/to/main/.yoke/install-manifest.json`.
Apply requires a clean target, preserves edited project contracts and strategy,
and does not fetch bundles, register a checkout or sync environment snapshots.
Managed source namespaces prune unchanged retired files; edited retired files
are preserved and released from management. Other managed namespaces retain
their prior hashes. See `yoke project refresh --help` for the full contract.

Source-dev/admin work also includes release builds, install-bundle and packet
rendering, server provisioning and repair, actor grants, migration and recovery.
These are separate from normal project onboarding; use the owning runbook and
registered command rather than internal Python admin modules. For a local source-built core, inspect the plan first:

```bash
yoke core build --checkout /absolute/path/to/yoke --dry-run
yoke core start --from-checkout /absolute/path/to/yoke --build
yoke core status --json
yoke core logs
yoke core stop
yoke core upgrade --from-checkout /absolute/path/to/yoke --build --dry-run
```

Core state lives under `~/.yoke/local-core`; `--image IMAGE` selects an
already-built private image. This source-dev/admin launcher does not pull a
public default image or grant normal operators direct database authority.

## Submitting a change

1. Branch and commit your change, following [AGENTS.md](AGENTS.md).
2. Open a pull request with tests for changed behavior and updated owning docs.
3. Sign the [CLA](CLA.md) on your first pull request by replying with the exact
   comment the automated check requests. The recorded signature covers later
   contributions.

Pull requests to `main`, including forks, trigger
[the CI workflow](.github/workflows/yoke-ci.yml): portable wheel builds,
repository contracts (changed-file Ruff, authored-file limits, generated
surfaces and bundle checks), sharded Python tests, browser-runtime tests and
a core-container build. Python versions and shard groups come from the
checked-in CI policy. GitHub may require maintainer approval before a new
contributor's workflow runs. The [CLA workflow](.github/workflows/cla.yml)
checks the contribution agreement separately.

Maintainers publish through the [release contract](docs/releases/README.md).
Private builds and distribution have their own
[fork guide](docs/public/projects/private-forks.md).

## Repository layout

| Path | Contents |
|---|---|
| `packages/yoke-core/` | Domain, API, DB, engines and contributor tools. |
| `packages/yoke-cli/` | Installed CLI, typed adapters and transport. |
| `packages/yoke-contracts/` | Shared interface, event and policy contracts. |
| `packages/yoke-harness/` | Installable hook and browser support. |
| `runtime/agents/`, `runtime/harness/` | Canonical roles, manifests and rendered adapters. |
| `runtime/api/`, `runtime/browser_runtime/`, `tests/` | API/browser/boundary verification. |
| `.agents/skills/yoke/` | Canonical situational skill knowledge. |
| `packs/` | Immutable reusable capability bundles. |
| `packaging/` | Pre-runtime installer and distribution metadata. |
| `docs/`, `.yoke/` | Public/source references and project policy/generated views. |
| `docs/teaching/` | [Teaching prototype](docs/teaching/README.md): what Yoke teaches, where and when, with evidence and gaps. |
| `.github/workflows/` | CI and hosted release execution. |

## License

Contributions use the terms of the [CLA](CLA.md). Yoke uses the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md)
(FSL-1.1-ALv2); each version converts to Apache 2.0 two years after release.
