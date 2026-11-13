# Back up and restore this machine

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Back up and restore this machine
<!-- /yoke:breadcrumbs -->

## Save a backup folder

Save this machine's Yoke configuration and credentials in one private folder:

```sh
yoke machine backup --to "$HOME/Backups/yoke-machine"
```

Choose a private folder, such as your iCloud secrets folder. The backup contains credential files;
it is not encrypted by Yoke. Repeating the command updates changed files and
removes files no longer included, so keep separate folders for historical copies.

The folder contains `manifest.json` and a `home/` tree. The manifest records each
file's home-relative name, original mode, size, and SHA-256. Keep them together.
Backup includes `~/.yoke/config.json`, `~/.yoke/secrets/`, and `~/.yoke/ssh/`
when present. It also includes home-relative copies of connection token/DSN
files and PostgreSQL tunnel identity files referenced by the configuration.
Missing referenced files are named and skipped. References outside your home
must be moved under it and updated in the configuration before backup.

Backup excludes `*.lock`, `*.stale*`, `YOKE_*_DSN_VALIDATION*`,
`yoke_validation_*.dsn`, `github-app-user-*.json`, browser `profile/` and
`identities/` trees, and `installer-live-tui/`. Symlinks refuse; use regular
files. Browser passwords stored as capability secrets remain included.

## Restore on a new Mac

On a new Mac, install Yoke first, make the folder available, and run:

```sh
yoke machine restore --from "$HOME/Backups/yoke-machine"
```

Both commands work without a configured control plane. Restore verifies every
included file before copying. A missing file or hash mismatch refuses with its
name; contents and diffs are never printed. Existing differing files refuse
unless you add `--replace`. Restored directories use mode `700` and files `600`.
Absolute credential and tunnel paths under the old home are updated for the
new home. Other configuration values remain as saved; review project checkout
locations if they moved.

## Verify health and authorize again

Restore runs `yoke doctor run --only connections` after copying. A failed or unavailable
Doctor returns a failure with recovery instructions; the copied files stay in
place. Run the named Doctor command to inspect and repair restored connection health.
Run `yoke github connect` to authorize GitHub again, and use
`yoke browser authorize --help` to sign into browser profiles again.

This folder protects machine configuration and credentials. Back up repositories,
application data, and the Universe separately; see
[Universe portability, backup, and restore](universe-portability.md).
