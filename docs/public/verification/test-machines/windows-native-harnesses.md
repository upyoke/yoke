# Native Windows harness installation

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows harness installation
<!-- /yoke:breadcrumbs -->

Complete [desktop setup](windows-native-host-provisioning.md#3-desktop-and-sign-ins)
before installing and signing in as the dedicated standard test user.

As the standard user install all harness CLIs from their vendors:

```powershell
irm https://claude.ai/install.ps1 | iex
npm.cmd install --global @openai/codex
irm 'https://cursor.com/install?win32=true' | iex
claude --version
codex --version
agent --version
```

Native installer downloads are decoded as UTF-8 from their raw response bytes.
Windows PowerShell can expose binary media as a byte array in `Content`; treating
that value as text can break execution or hash a conversion instead of the script.
Compare raw bytes before attributing a checksum refusal to changed vendor code.
Malformed UTF-8 refuses with `windows_vendor_installer_utf8_invalid`; inspect
the vendor response encoding before retrying. The installer has not executed.

Sources: [Claude](https://code.claude.com/docs/en/setup),
[Codex on Windows](https://developers.openai.com/codex/windows/),
[Cursor native CLI](https://cursor.com/docs/cli/installation).
Install/launch each vendor's desktop app as the same user. Agents finish setup
and navigation; Ben types his own harness/GitHub passwords. Before goldens,
prove real CLI requests and visible signed-in desktop apps; installs/versions
alone do not prove readiness. Follow [native browser identities](windows-browser-identities.md).
