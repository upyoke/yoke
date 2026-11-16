# Public installer sources

Run `yoke dev run -- python3 packaging/public-installer/build.py` after editing
`source/*.py.inc`, then run it again with `--check`. Commit the fragments and
the generated `install.py` together. Each fragment has one concern and stays
within the repository's `file_line_limit`; the generated download remains one standalone Python program.

Before a candidate exists, bootstrap uses the embedded shared `platform_file_lock`
primitive to exclude release collection during generation creation and lease
acquisition. It keeps the lease file open through installation and activation.

The installer uses uv to resolve one exact product release into a private tool
environment, then runs that candidate's own `yoke_cli.config.cli_release_runtime`
with the candidate's Python, so the release being installed, not the installer
version, decides the on-disk layout. That module verifies the candidate and
atomically publishes the stable launcher. Its `main` takes exactly
`root generation bin_dir version`; installers already in use depend on that
interface, so keep it unchanged. Serving a release before the matching installer
is therefore harmless. Before activation, `helper_sources` runs uv with
umask `022`, checks every credential-helper source with the candidate's own
bundle guard, and on group- or other-writable files cleans only the
`yoke-cli` and `yoke-contracts` cache entries and reinstalls once. Commands lease their selected environment before
importing its code; retirement checks leases and process snapshots. The relay
and manual update both reuse this path. No service or public download is added.

Installer colors use 24-bit SGR only when `COLORTERM` is `truecolor` or `24bit`;
other color terminals use their basic ANSI palette. Body text uses the terminal's
default foreground so the completion instructions work on light backgrounds.
`NO_COLOR`, non-terminal output and `TERM=dumb` disable color.

The native Windows bootstrap is `install.ps1`; `--channel`, `--version`,
`--dry-run`, `--yes` and `--no-setup` pass to the Python helper. `--wsl` explains
the Ubuntu alternative without installing. `YOKE_INSTALL_BASE_URL` selects the
distribution origin (including a local CI HTTP server). Windows needs Python
3.12+ for non-blocking process pipes; uv supplies it. macOS/Linux remain 3.11+.
Package `requires-python` stays at the common 3.11 floor because it cannot
express platform-specific floors; both the CLI and installer reject Windows 3.11.

Constrained PowerShell refuses before bootstrap and gives a download-to-file
Python route that does not use `iex`; application-control restrictions still
apply. Paths exceeding MAX_PATH refuse with the `LongPathsEnabled` recovery.
Windows PATH inspection reads `HKCU\Environment\Path`; repair adds uv's bin
only when missing. Uninstall retains that shared entry because uv owns it.
This work is preparation for native Windows acceptance, not a support claim.
