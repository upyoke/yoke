# Contributing to Yoke

Yoke is [Fair Source](https://fair.io) software: the source is published to
read, audit, and contribute to, while the product you run is the packaged
install. This document covers how those two relate and how a change gets in.

## The packaged install is the product

Yoke installs as lockstep packaged wheels (`yoke-cli`, `yoke-contracts`,
`yoke-harness`, `yoke-core`) via the public installer:

```bash
curl -fsSL https://api.upyoke.com/install | bash
```

Install, upgrade, and onboarding details live in
[docs/local-setup.md](docs/local-setup.md).

## Cloning is for reading and contributing — it activates nothing

`git clone` gives you the full source to read and audit. It changes nothing
about your machine's Yoke: the installed `yoke` keeps running its packaged
wheels no matter how many checkouts exist on disk. Binding a checkout is a
separate, explicit step (below) — never a side effect of cloning.

`yoke status` states the current binding on its `install:` line:

```text
install: packaged wheel 1.4.0             # the packaged product is running
install: source checkout /Users/you/yoke  # an explicitly activated checkout is running
```

## Run the tests without touching your install

The checkout is a uv workspace. Sync it, then run the canonical test target
inside the checkout-local venv — your installed `yoke` is not involved:

```bash
uv sync --all-packages --all-groups
uv run python3 -m yoke_core.tools.watch_pytest -- runtime/api/ runtime/harness/ tests/
```

- Pass the two anchors exactly as shown — never bare `runtime/`, which breaks
  pytest conftest collection (the wrapper refuses it with a repair message).
- For a focused run, pass specific file or directory paths after `--`.
- Tests run in parallel by default (pytest-xdist `-n auto`); pass
  `--no-parallel` after `--` to opt out.
- The suite starts its own disposable Postgres cluster on first use; no
  database setup is required beyond having the Postgres server binaries
  (`initdb`, `pg_ctl`) on `PATH` — e.g. `brew install postgresql@17` on
  macOS or `apt install postgresql` on Debian/Ubuntu.

## Activate a source checkout (explicit source-dev step)

Activate a checkout only when the `yoke` command itself should run your
checkout's code — for example, to exercise a CLI change end to end:

```bash
yoke dev setup /path/to/yoke --editable-install --yes
```

`yoke dev setup` owns source-link repair, the editable install, and the
optional local-Postgres admin connection (`--with-test-postgres`,
`--set-active-env`, DSN flags — see `yoke dev setup --help`). Its editable
install replaces pip's absolute-path artifacts with a config-driven shim, so
a later checkout move only needs the machine-config path updated, with no
reinstall. Verify the result:

```bash
yoke status    # install: source checkout /path/to/yoke
```

**The editable-install trap:** the editable install uninstalls the packaged
wheels the running process is executing from. Never repoint the `yoke`
launcher while any yoke process — a wizard, a long-running command — is
mid-flow; `yoke dev setup` itself defers the editable install to its last
step for exactly this reason. To return to the packaged product, rerun the
curl installer.

## Submitting a change

1. Fork, branch, commit. The in-repo contributor rulebook is
   [AGENTS.md](AGENTS.md) — the always-on rule set for human and agent
   contributors alike (`CLAUDE.md` and `CODEX.md` are compatibility pointers
   to it).
2. Open a pull request that includes tests for the change.
3. **Sign the CLA on your first pull request.** An automated comment links to
   [CLA.md](CLA.md); you sign by replying on the pull request with the exact
   comment it asks for. The signature is recorded durably and covers all your
   future contributions — returning contributors are recognized automatically
   and never asked again.

## License

Yoke is Fair Source, source-available under the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md)
(FSL-1.1-ALv2). Each version converts to the Apache License, Version 2.0 two
years after its release. Your contributions are licensed to the project under
the terms of the [CLA](CLA.md).
