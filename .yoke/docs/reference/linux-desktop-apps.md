# Linux desktop version detection

The machine relay detects Claude Desktop's installed `claude-desktop` Debian
package on Ubuntu and Debian, on x86_64 and arm64. It detects Cursor's installed
`cursor` Debian or RPM package. Package queries read installed metadata; they
never start the desktop app. Removed Debian packages with residual configuration
do not count as installed.
Debian epochs and package revision suffixes are removed before the application
version enters the existing floor check; prerelease labels remain prereleases.

For Cursor installs outside the package manager, the relay reads
`resources/app/package.json` beneath `/usr/share/cursor` or `/opt/cursor`.
It uses `cursorVersion`, because `version` identifies the upstream VS Code build.
An extracted install can also be discovered through its executable on PATH or
a Cursor desktop entry.

Portable Cursor AppImages are discovered through `cursor` on PATH, a Cursor
desktop entry under the XDG application directories, `~/Applications`,
`~/.local/bin/cursor`, or `/opt/cursor.AppImage`. The relay reads the embedded
version file with `unsquashfs -cat`; it does not execute the AppImage, even with
an extraction flag. Install `squashfs-tools` to enable this reader. Missing tools,
corrupt images, unreadable metadata, and package query failures produce named
probe diagnostics with recovery instructions. Versions are never inferred from
the download filename.

Both relay inventory and single-surface checks use this probe and feed the
existing surface version floors. macOS continues to read app bundle plists.
The probe does not inspect Windows installations or reach into Windows from WSL.

Supported vendor formats: [Claude Desktop installation](https://support.claude.com/en/articles/10065433-install-claude-desktop)
and [Cursor Linux installation](https://cursor.com/docs/get-started/quickstart).
