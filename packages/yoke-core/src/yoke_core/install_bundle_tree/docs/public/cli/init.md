# Create a local universe

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [CLI and config](index.md) > Create a local universe
<!-- /yoke:breadcrumbs -->

`yoke init` creates a free universe on this machine: embedded PostgreSQL,
the control-plane schema, an organization identity card, the first human
administrator, and a machine-config connection named `local`.

## Initialize

```text
yoke init --local --admin-name "Your Name"
yoke status
```

The universe is reachable on this machine only. Use self-hosted mode or
Hosted beta (upyoke.com) for multiple machines or teammates.
See [Modes](../start/modes.md) for prerequisites and alternatives.

An existing active connection stays selected. Add `--activate` when you
intend to make local active. `--org-name` sets the identity-card name.
`--force` replaces a conflicting `local` machine-config connection; inspect
that connection before choosing it.

## Repair and inspect

Run `yoke init --help` for the installed flags. `--config` selects a
machine-config file and `--json` selects structured output.
Re-running init can restart the local database while preserving the active
connection. Follow [Local connection repair](../verification/local-connection-repair.md)
when local is unreachable or the selected connection is wrong.
