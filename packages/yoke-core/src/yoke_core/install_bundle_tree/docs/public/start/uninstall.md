# Remove Yoke

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Get started](index.md) > Uninstall
<!-- /yoke:breadcrumbs -->

Choose what to preserve before removing Yoke from this machine or its projects.
The uninstall command reports each cleanup result and names recovery on failure.

## Uninstall

```bash
yoke uninstall
```

On a machine holding a local universe or a self-host server, the first output
warns that uninstall deletes its only copy of the universe data. Choose **back
up first** to run `yoke universe export` for each owned universe, or **uninstall
without backing up**. There is no automatic backup. Uninstall's backups land
in the current directory; run uninstall outside the machine home. A manual
`yoke universe export` defaults to the machine Yoke home exports folder;
pass `--out PATH` outside that home before uninstall. A failed export stops
removal and names the recovery. Hosted-only clients see no data warning.

Next, the command lists registered checkouts with a Yoke install manifest.
Choose all, none, or a selection to also run `yoke project uninstall` on.
A Git checkout must be on the project's default branch before its layer is
removed. When the Yoke install that owns a project no longer answers, its layer
is still removed and committed on the current branch, with a warning to merge
that commit into the default branch.
It then removes the relay and its workers, the selected project layers, Yoke's
GitHub credentials and checkout helpers, its machine-wide hooks and their Codex
trust, and the approval, `yoke` allow-entry and folder-trust settings it wrote into
Claude Code, Codex and Cursor; stops the hook evaluator, local UI and embedded Postgres,
tears down local self-host stacks and their universe volumes, and deletes the
machine home (`~/.yoke` or `YOKE_MACHINE_HOME`). A harness setting you changed after Yoke
wrote it is left in place and reported. Docker is only checked when this
machine runs a self-host install. No further confirmation is required. Finally a detached
worker removes the immutable CLI releases and launcher after commands release
their environments. Its result log is printed by the command.

Each step reports done, skipped with a reason, or failed with a named recovery.
Independent cleanup continues after a failure; the machine home and CLI stay
available when cleanup needs recovery. Fix the reported problem and retry.
Source-checkout CLI installs refuse; retire those through your source-dev workflow.

For unattended removal, make the same choices explicitly:

```bash
yoke uninstall --projects all --yes                 # hosted-only client
yoke uninstall --backup --projects none --yes       # machine holding data
yoke uninstall --no-backup --projects ~/work/app --yes
```

`--projects` accepts all, none, or comma-separated registered checkout paths.
`--yes` never selects data loss or a project choice for you. The command leaves
uv, the PATH line in your shell profile, and the GitHub App installed; remove
the App in GitHub settings if desired. Push the removal commits made in the
chosen checkouts. Project-owned edits and strategy documents are preserved by
the existing project uninstall.

## Remove one project layer

```text
yoke project uninstall /path/to/checkout
```

It removes the installed layer and only proven installer-owned, exclusive
checkout registration and exact folder trust; entries that grant no trust stay
as they are. Install never trusts a parent folder, so uninstall neither reports
nor changes trust on one. Shared roots, Git worktrees, edited entries and unknown ownership
are preserved with named reasons.
The removal commit records only files Git already tracked; ignored local views,
including the install manifest, never enter history. Strategy documents stay on
disk, untracked.
A partial cleanup exits nonzero and retains its manifest: resolve the named
ownership or sharing issue, then rerun the same command. Credentials, other
projects, shared tools and server history stay intact; source checkouts refuse.

Retiring lanes removes their path-owned folder trust before machine uninstall.
To remove older residue while keeping Yoke installed, run
`yoke harness lane-config sweep --dry-run`, then the same command without
`--dry-run`. Each changed config receives a timestamped backup beside it;
paths outside managed roots remain. See
[harness cleanup](../agents/harness-discovery.md#retired-lane-settings).

## Related

- [Install and onboard](install.md)
- [Project installation](project-install.md)
- [Get started](index.md)
