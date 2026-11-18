# Native Windows harness installation

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows harness installation
<!-- /yoke:breadcrumbs -->

Complete [desktop setup](windows-native-host-provisioning.md#3-desktop-and-sign-ins)
before installing and signing in as the dedicated standard test user.

As the standard user install all harness CLIs from their vendors:

```powershell
function VendorScript($uri) {
 $response=Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 30 -ErrorAction Stop
 $bytes=$response.RawContentStream.ToArray()
 $text=([Text.UTF8Encoding]::new($false,$true)).GetString($bytes).TrimStart([char]0xFEFF)
 [ScriptBlock]::Create($text)
}
& (VendorScript 'https://claude.ai/install.ps1')
npm.cmd install --global @openai/codex
& (VendorScript 'https://cursor.com/install?win32=true')
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
If Cursor architecture detection fails with CIM/WMI access denied under SSH,
stop and inspect the partial installer directory and user PATH before retrying.
Its initializer can mutate both before the architecture check. An interactive
token must be proved separately; do not elevate the standard test user.
Yoke runs Cursor installation and its post-install probe through the existing
standard user's interactive desktop task. Ordinary probes and the other CLI
installers use SSH. A missing interactive session refuses installation.

Install desktop apps using the vendor's documented package context, then launch
and sign in as the standard test user. Claude's direct MSIX includes a service
and requires administrator provisioning; non-admin `Add-AppxPackage` can refuse
with `0x80073D28`. OpenAI's machine provisioning requires its offline license.
Follow [Claude deployment](https://support.claude.com/en/articles/12622703-deploy-claude-desktop-for-windows)
and [OpenAI deployment](https://learn.chatgpt.com/docs/enterprise/windows-deployment.md);
keep WSL and VirtualMachinePlatform disabled. Provisioning alone does not prove
standard-user registration, launch or authentication.

Agents finish setup and navigation; Ben types his own harness/GitHub passwords. Before goldens,
prove real CLI requests and visible signed-in desktop apps; installs/versions
alone do not prove readiness. Follow [native browser identities](windows-browser-identities.md).
