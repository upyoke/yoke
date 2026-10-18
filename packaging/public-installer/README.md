# Public installer sources

Run `yoke dev run -- python3 packaging/public-installer/build.py` after editing
`source/*.py.inc`, then run it again with `--check`. Commit the fragments and
the generated `install.py` together. Each fragment has one concern and stays
under 350 lines; the generated download remains one standalone Python program.

The installer uses uv to resolve one exact product release into a private tool
environment. The candidate's `cli_release_runtime` verifies it and atomically
publishes the stable launcher. Commands lease their selected environment before
importing its code; retirement checks leases and process snapshots. The relay
and manual update both reuse this path. No service or public download is added.
