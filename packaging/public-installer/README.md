# Public installer sources

Run `yoke dev run -- python3 packaging/public-installer/build.py` after editing
`source/*.py.inc`, then run it again with `--check`. Commit the fragments and
the generated `install.py` together. Each fragment has one concern and stays
under 350 lines; the generated download remains one standalone Python program.

The installer uses uv to resolve one exact product release into a private tool
environment. The build embeds the shared `cli_release_runtime` source so bootstrap
also works when a selected wheel does not carry that module. Its standalone copy
verifies the candidate and atomically
publishes the stable launcher. Commands lease their selected environment before
importing its code; retirement checks leases and process snapshots. The relay
and manual update both reuse this path. No service or public download is added.
