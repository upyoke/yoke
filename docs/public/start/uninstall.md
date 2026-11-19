# Remove Yoke

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Installation reference](index.md) > Uninstall
<!-- /yoke:breadcrumbs -->

Choose what to preserve before removing Yoke from this machine or its projects.
The uninstall command reports each cleanup result and names recovery on failure.

## Uninstall

```bash
yoke uninstall
```

On a machine holding a local universe or a self-host server, the first output
warns that uninstall deletes its only copy of the local universe data or the
self-hosted server data. Choose **back up first** to run `yoke universe export`
for each owned universe, or **uninstall without backing up**. Any other answer
cancels with exit 0 and changes nothing. There is no automatic backup. Uninstall's backups land
in the current directory; run uninstall outside the machine home. Each archive
is named for the universe it holds, `local-<org>-universe-<stamp>.tar` or
`self-host-<bundle-folder>-<org>-universe-<stamp>.tar`, and each backup line
prints its full path. An existing file at that path stops the backup. A manual
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
trust, and the folder-trust settings it wrote into
Claude Code, Codex and Cursor. It restores approval modes replaced during setup
and removes approval keys setup added, including values Claude Code wrote in
answer to them: an `auto` default it switched to, and the bypass-warning
acceptance when it was not there before setup. It also removes the `hooks`
object, or the whole settings file, when Yoke created it and it is now empty. It stops the hook evaluator, local UI and embedded Postgres,
tears down local self-host stacks and their universe volumes, and deletes the
machine home (`~/.yoke` or `YOKE_MACHINE_HOME`). The system temporary directory
must be outside that home; uninstall refuses before removing anything when it
is not. A harness setting you changed after Yoke
wrote it is left in place and reported. Docker is only checked when this
machine runs a self-host install. No further confirmation is required. Finally a detached
worker removes the immutable CLI releases and launcher after commands release
their environments, then Yoke's PATH blocks. The command prints the releases
folder it removes and its result log, in the system temporary directory. If
that removal fails, `yoke` may already be gone, so the log names a command that
removes the folder without it: `Remove-Item -LiteralPath '\\?\<folder>' -Recurse
-Force` on Windows, `rm -rf '<folder>'` elsewhere.

Each step reports done, skipped with a reason, or failed with a named recovery.
On macOS, systemd Linux and Windows, uninstall checks saved relay services
(launchd jobs, systemd units, scheduled tasks) even after their connection was
removed. It proves their machine-home ownership and verifies that the services
have stopped. An unreadable service or failed stop
retains recovery files.
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
`--yes` never selects data loss or a project choice for you.
The detached worker removes Yoke's marked PATH blocks from all supported startup
files, including `.zshenv` and `.bashrc`, and preserves unrelated shell text. A
startup file Yoke created, and each folder it made for one (such as
`~/.config/fish`), is deleted once only its block is left; a file that existed
before keeps its bytes, even when empty. Folders the relay made for its systemd
unit go with the harness settings once empty. Uninstall removes each selected
project's clean Yoke lane worktrees (their branches stay) and refuses before
changing anything while a lane holds uncommitted work. It leaves uv, user-owned
PATH entries, and the GitHub App installed, and prints uv's own removal
commands for when nothing else uses uv; remove the App in GitHub settings if desired. Push the removal commits made in the
chosen checkouts. Project-owned edits and strategy documents are preserved by
the existing project uninstall.

## Remove one project layer

```text
yoke project uninstall /path/to/checkout
```

For an installed layer, it removes only proven installer-owned, exclusive
checkout registration and the exact folder trust Yoke recorded writing. Trust
Yoke did not write, such as trust you granted in a harness or on a parent
folder, is neither changed nor reported. A trust entry you edited after Yoke
wrote it stays and is reported; uninstall still completes. A checkout mapping
that onboarding or install wrote is installer-owned; one made by
`yoke project register` stays, and the warning names the machine config entry
to delete before you rerun. Shared roots, Git worktrees outside the lanes
directory and unproven registration are preserved with named reasons. A Yoke
lane worktree of an open item refuses with `project_uninstall_open_lanes` before
anything changes; `--remove-lanes` removes clean lanes first. The default-branch
check asks the connection that registered the checkout, not the active one.
A checkout registered on one connection only is retired from that connection
whichever connection is active, so projects from different universes that share
a project number uninstall independently; a checkout registered on two
connections is preserved as `checkout_shared_with_other_connection`. Each
reason is reported once, however many harnesses it covers.
Each run lands one removal commit, recording only files Git already tracked;
ignored local views, including the install manifest, never enter history. A
complete cleanup deletes the generated `.yoke/BOARD.md*` views and names every
`.yoke` path it leaves untracked: strategy documents stay on disk under
`project_uninstall_strategy_views_kept`, anything else under
`project_uninstall_local_files_kept`.
A partial cleanup exits nonzero and keeps its manifest and `.yoke/.gitignore`,
so the checkout stays clean: resolve the named ownership or sharing issue, then
rerun the same command. Credentials, other
projects, shared tools and server history stay intact; source checkouts refuse.

If installation failed before writing a `.yoke` layer, onboarding still keeps
the checkout registered. The same command removes that exact registration
only after checking for uncommitted work and shared checkout scope; it changes
no source files or folder trust. If the selected folder still exists but is no
longer a Git repository, the command skips Git guards and removes only its exact
registration (on the active connection, else its only one), preserving every file, layer, trust
entry and other registration. Missing folders are outside this cleanup path.
A `.yoke` directory in a Git repository without its manifest
refuses with `project_uninstall_manifest_missing`: recover the manifest before
retrying instead of guessing which files Yoke owns.

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

## Turn hooks off for one folder

Use `yoke folder disable PATH` to stop hooks in that folder and its subfolders
on this machine while keeping Yoke installed. It works for registered projects
and other folders. `yoke status` reports the disabled folder;
`yoke folder enable PATH` restores hooks unless an ancestor is still disabled.
See [What Yoke sends](../agents/harness-discovery.md#what-yoke-sends).
