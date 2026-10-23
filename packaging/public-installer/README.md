# Public installer sources

Run `yoke dev run -- python3 packaging/public-installer/build.py` after editing
`source/*.py.inc`, then run it again with `--check`. Commit the fragments and
the generated `install.py` together. Each fragment has one concern and stays
under 350 lines; the generated download remains one standalone Python program.

The installer uses uv to resolve one exact product release into a private tool
environment. The build embeds the shared `cli_release_runtime` source so bootstrap
also works when a selected wheel does not carry that module. Its standalone copy
verifies the candidate and atomically
publishes the stable launcher. Before activation, `helper_sources` runs uv with
umask `022`, checks every credential-helper source with the candidate's own
bundle guard, and on group- or other-writable files cleans only the
`yoke-cli` and `yoke-contracts` cache entries and reinstalls once. Commands lease their selected environment before
importing its code; retirement checks leases and process snapshots. The relay
and manual update both reuse this path. No service or public download is added.

Installer colors use 24-bit SGR only when `COLORTERM` is `truecolor` or `24bit`;
other color terminals use their basic ANSI palette. Body text uses the terminal's
default foreground so the completion instructions work on light backgrounds.
`NO_COLOR`, non-terminal output and `TERM=dumb` disable color.
