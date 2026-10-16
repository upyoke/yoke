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
It then removes the relay and stops its workers, removes the selected project
layers, disconnects Yoke's GitHub credentials and checkout helpers, removes
Yoke's entries from your Cursor user hooks (`~/.cursor/hooks.json`), reverts the
approval and folder-trust settings Yoke wrote into Claude Code, Codex, and
Cursor, stops the hook evaluator, local UI and embedded Postgres, tears down
local self-host stacks including their universe volumes, and deletes the machine home
(`~/.yoke` or `YOKE_MACHINE_HOME`). A harness setting you changed after Yoke
wrote it is left in place and reported. Docker is only checked when this
machine runs a self-host install. No further confirmation is required. Finally a detached
worker removes the CLI with `uv tool uninstall yoke-cli` after the uninstall
process exits. Its result log is printed by the command.

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

## Related

- [Install and onboard](install.md)
- [Project installation](project-install.md)
- [Get started](index.md)
