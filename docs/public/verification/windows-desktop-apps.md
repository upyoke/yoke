# Windows desktop version detection

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Windows desktop apps
<!-- /yoke:breadcrumbs -->

On native Windows the machine relay detects Claude Desktop, the Codex desktop
app and Cursor from installed registry metadata. It never starts the apps and
never runs PowerShell, so each probe finishes within the relay poll.

| Surface | Windows identity | Version read from |
| --- | --- | --- |
| `claude-desktop` | MSIX package family `Claude_pzs8sxrjxfjjc` | package full name |
| `codex-desktop` | MSIX package family `OpenAI.Codex_2p2nqsd0c76g0` | package full name |
| `cursor-desktop` | `Uninstall` entry with DisplayName `Cursor (User)` or `Cursor` | `DisplayVersion` |

MSIX packages are read from the signed-in user's package repository,
`HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages`.
Its subkeys are the package full names that `Get-AppxPackage` reports; when
several versions are registered the newest wins. The `OpenAI.CodexPrimaryRuntime`
package is a runtime, not the desktop app, and does not count. Win32 installs
are read from the HKCU, then the HKLM `Uninstall` key.

An app that is not installed reads `missing` with `desktop_app_missing`, naming
the package family or DisplayName that was looked for. Install the app as the
same Windows user the relay runs as. A registry key the relay cannot read, or an
`Uninstall` entry without a readable `DisplayVersion`, reads `error` with
`desktop_metadata_unreadable`; check the user's registry permissions or reinstall
the app.

macOS reads app bundle plists, and [Linux](linux-desktop-apps.md) reads
packages and AppImages. Every platform feeds the same surface version floors.

## Related

- [Verification](index.md)
- [Linux desktop applications](linux-desktop-apps.md)
