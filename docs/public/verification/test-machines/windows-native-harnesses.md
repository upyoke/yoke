# Native Windows harness installation

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows harness installation
<!-- /yoke:breadcrumbs -->

Complete [desktop setup](windows-native-desktop.md)
before installing and signing in as the dedicated standard test user. Follow
the [normal-user installation rule](index.md#install-as-the-test-user).

Open built-in **Windows PowerShell 5.1** as that user: **Start > Run**, then
`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` (or
`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`). The `v1.0`
directory is also the normal path for version 5.1. Confirm
`$PSVersionTable.PSVersion`; these steps do not require a PowerShell 7 download
or an administrator shell. PowerShell 7, if separately installed, uses `pwsh.exe`.

As the standard user install all harness CLIs from their vendors:

```powershell
function VendorScript($uri) {
 $response=Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 30 -ErrorAction Stop
 $bytes=$response.RawContentStream.ToArray()
 $text=([Text.UTF8Encoding]::new($false,$true)).GetString($bytes).TrimStart([char]0xFEFF)
 [ScriptBlock]::Create($text)
}
& (VendorScript 'https://claude.ai/install.ps1')
$claudeDir=Join-Path $env:USERPROFILE '.local\bin'
& (Join-Path $claudeDir 'claude.exe') --version
if($LASTEXITCODE -ne 0){throw 'Claude installation unverified'}
$key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
try {
 $raw=[string]$key.GetValue('Path','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
 $kind=if($key.GetValueNames() -contains 'Path'){$key.GetValueKind('Path')}else{[Microsoft.Win32.RegistryValueKind]::ExpandString}
 $entries=@($raw -split ';'|ForEach-Object {[Environment]::ExpandEnvironmentVariables($_).TrimEnd('\')})
 if($entries -inotcontains $claudeDir){$key.SetValue('Path',($raw.TrimEnd(';')+';'+$claudeDir).TrimStart(';'),$kind)}
} finally {$key.Dispose()}
& (VendorScript 'https://chatgpt.com/codex/install.ps1')
& (VendorScript 'https://cursor.com/install?win32=true')
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
claude --version
codex --version
agent --version
```

Native installer downloads are decoded as UTF-8 from their raw response bytes.
Finish each successful install before starting another. Claude can report
success while warning that `.local\bin` is missing from PATH; preserve existing
entries and registry value kind when adding it. Existing GUI processes retain
their inherited PATH. Verify command discovery in a fresh desktop shell.
A probe that rebuilds its PATH does not prove GUI inheritance.
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
Yoke uses the standard user's interactive desktop task for Cursor and Codex
installation and for probes that include Codex. OpenSSH Redirection Guard
can block the Codex vendor installer's per-user launcher junction.
A missing interactive session refuses the operation.

Install desktop apps from their public downloads in the standard test user's
desktop session:

- **Claude Desktop:** Ben opens [Claude's download page](https://claude.com/download)
  in the test user's browser, downloads the Windows installer and runs it.
- **OpenAI desktop app with Codex:** start from the [ChatGPT desktop download](https://chatgpt.com/download/)
  and follow the Windows install as the test user. Select **Codex** after
  signing in.
- **Cursor:** choose the Windows **User** installer for the host architecture
  from [Cursor's download page](https://cursor.com/download). Run it as the
  test user.

Keep WSL and VirtualMachinePlatform disabled on this fixture.

Agents finish setup and navigation; Ben types his own harness/GitHub passwords. Before goldens,
prove real CLI requests and visible signed-in desktop apps; installs/versions
alone do not prove readiness. Follow [native browser identities](windows-browser-identities.md).

## Sign in and prove each installed surface

Update [capability tags](host-provisioning.md#register-capability-tags)
after proving each advertised desktop sign-in or signing it out.

Use the standard `yokeqa` Windows desktop, not an administrator or controller
profile. In **Start > All**, open the installed **Claude**, **Cursor** and
OpenAI desktop app; confirm the actual package identity and displayed app name
(the observed OpenAI package appeared as **ChatGPT** in Start). Choose each
app's sign-in action and complete its official browser flow with the intended
Anthropic, Cursor or OpenAI account/workspace. A Start web search or download
page is not the installed app; do not reinstall merely to reach sign-in.

In that user's Windows terminal, authenticate the CLIs separately:

```powershell
claude auth login
codex login
agent login
codex login status
agent status
```

If that terminal still has an older PATH, use the installed launchers directly:

```powershell
& "$env:USERPROFILE\.local\bin\claude.exe" auth login
& "$env:APPDATA\npm\codex.cmd" login
& "$env:LOCALAPPDATA\cursor-agent\agent.ps1" login
```

Follow [Claude authentication](https://code.claude.com/docs/en/authentication),
[official OpenAI authentication](https://learn.chatgpt.com/docs/auth?surface=cli)
and [Cursor authentication](https://cursor.com/docs/cli/reference/authentication).
Ben completes passwords, MFA and account approval in the displayed official
flows. Preserve auth caches privately; never print/copy them into the guide,
chat, captures or repository. Do not substitute new API keys for these sign-ins.
Sign into GitHub in the native browser when required by the case. Close completed
auth tabs, retain each signed-in app, and run a small real request through each
CLI before sealing goldens. Record the visible app and request outcome without
credentials; versions and login-status commands alone are insufficient.

The canonical golden checks also require **Claude bypass accepted**, separately
from login. In an empty QA folder under this dedicated user's profile, the
operator runs `& "$env:USERPROFILE\.local\bin\claude.exe" --dangerously-skip-permissions`
and personally reviews the one-time warning. Bypass mode allows commands without
Claude's usual permission prompts; accept only under the project's lab policy.
Exit without submitting a task afterward. The probe requires the actual recorded
boolean `skipDangerousModePermissionPrompt=true` in that session's Claude config;
do not write the preference directly or weaken the check to seal a golden.
Golden capture includes `.claude/settings.json`, so reset restores the acceptance.
Windows packaged-app containers (`AppData/Local/Packages`), the per-user data
store service's open database (`AppData/Local/Comms`) and Claude desktop
data (`AppData/Local/Claude-Data`) remain live, like browser identities and locked
registry hives; their app settings are not restored from the golden. Copy failures
remain fatal, name robocopy's first failing files in the refusal, and retain a
private robocopy log under `AppData/Local/YokeQa`.
Goldens also retain raw User PATH values, registry types and absence. Reset
validates that metadata before mirroring the profile and verifies it afterward;
older goldens without it require recapture rather than guessing a registry type.
Before mirroring, reset stops the test user's processes that run from the
resettable profile or WindowsApps, checking ownership under that account. It
leaves executables in preserved directories running. Windows launches the Widgets
packages (`MicrosoftWindows.Client.WebExperience`, `Microsoft.WidgetsPlatformRuntime`,
and `Microsoft.StartExperiencesApp`) and the Microsoft Store package
(`Microsoft.WindowsStore`) on its own. Every process in these packages stays
running through reset because its state lives in preserved `AppData/Local/Packages`.
A failed SSH process
discovery names the session to check. Desktop-session stops relist until clear;
one still running at 20 seconds refuses `windows_reset_profile_process_running`.
After restore, reset reopens them there and reports `profile_processes_stopped`
and `desktop_apps_relaunched`; an app that fails to reopen is named in
`desktop_apps_relaunch_failed` without failing reset. For a sharing or
memory-mapped-file error under `.codex`, close Codex and retry the reset.
Goldens hold no links (`/XJ`) and `/MIR` purges profile links the golden lacks,
so the mirror excludes Windows' own System-marked profile compatibility
junctions (`My Music`, `Application Data` and similar). After the mirror, reset
removes any other leftover link and records it as `stale_links_removed`. It then proves no uv-managed Python the
golden lacks remains under `AppData/Roaming/uv/python`, refusing with
`windows_reset_uv_state_left` and the path otherwise. A failed shell-preconfigured
console install keeps the last 40 lines of its stdout and stderr in `recovery`.
Reset also removes `AppData/Local/YokeQaMission` scratch that the running
execution does not own, so a mission aborted before walk-end leaves nothing
behind; a removal it cannot finish refuses `windows_reset_mission_scratch_left`.
Goldens hold no `.yoke-stage-*` folders or uv's `HKCU\Software\Python\Astral`
key. Capture refuses `windows_profile_not_pristine` while either exists; reset
removes both, keeping its own stage folder, and fails with that code and
`profile_residue` if either survives. For an older golden: reset, then recapture.

## Verified standard-user transfer

Standard-user file uploads and large desktop/SSH scripts also use verified SFTP,
including small files. Their unique staging directory lives directly beneath the
resolved user profile, with protected grants only for that user, SYSTEM and
Administrators. Profile ancestors, file ownership, length and SHA256 are checked
before use. Each staging operation has a 90-second budget, followed by the
caller's execution budget and thirty seconds for exact cleanup. An SSH timeout
or exit 255 preserves staging because guest completion is uncertain; inspect
`staging_diagnostics` before recovery. Desktop acquisition failures also retain
`desktop_diagnostics` with the exact token, file hashes and cleanup outcome, and
preserve the original failure if cleanup fails. This does not establish that
optional framed stdin is reliable on the actual lab machine.

## First Tailscale login and bootstrap desktop

If private RDP is unavailable, use the existing key-only SSH bootstrap route;
keep public TCP/UDP3389 blocked. Keep the lab on while the item needs setup,
sign-ins or QA; do not impose a countdown or idle shutdown. Run:

```text
ssh -F none -i KEY -o BatchMode=yes -o ExitOnForwardFailure=yes -o ControlMaster=no -o ControlPersist=no -o ControlPath=none -o UserKnownHostsFile=KNOWN_HOSTS -o HostKeyAlias=VM_RESOURCE_ID -N -L 127.0.0.1:3390:127.0.0.1:3389 yokeqa@BOOTSTRAP_HOST
```

Use Yoke's known_hosts and full VM resource ID; verify the SSH host key.
In Windows App connect to `127.0.0.1:3390`, **Ask when required**, user `yokeqa`,
no gateway or administrator session. Disable clipboard, printer, smart-card,
microphone, camera and folder redirection. Compare the RDP certificate's SHA256
with the certificate independently observed through that verified SSH tunnel;
do not enable blanket **Always trust**. Never reuse a saved Administrator entry.
The generated password is in the private file reported by `desktop-access`;
for this lab its custody is
`~/.yoke/secrets/capability-secrets/yoke/test-machine_windows-native-lab/desktop_password`.
The operator enters it only in the RDP client, never chat, argv or screenshots.
This bootstrap is the one step that needs a person in an RDP client; once
autologon is proven, agents drive the desktop without one (see
[driving desktop apps](#driving-desktop-apps)). A person who only needs to look
can run `yoke test-machine desktop-access --test-machine VM --view`, which
opens FreeRDP over the same route with the password on stdin.

Inside Windows choose **Start > Tailscale > Get Started**, then sign in with the
existing tailnet account and approve the expected lab device. Accept terms
personally when shown. Stop on an unexpected account, hostname or duplicate
device; do not reset/delete devices or invent an auth key. An approved SYSTEM
`up` may instead print an official AuthURL for the operator's existing browser;
a URL or successful GUI login still needs independent SYSTEM/private-route proof.
Complete [tray startup handling and two cold boots](windows-native-desktop.md#tray-startup-and-autologon)
before treating the private desktop as persistent. Close completed auth tabs,
leave apps authenticated, disconnect without Windows sign-out, terminate the
local forward when it is no longer needed. Once all setup, sign-ins and QA
finish, deallocate the VM, verify its actual power state and report it.

## Driving desktop apps

QA walkers drive any native app on the lab, such as Codex Desktop or Claude
Desktop, with no RDP session and no Windows App on the controller. Use the
walk's mission flags:

```text
yoke qa mission host-command FLAGS --gui-session -- explorer.exe "shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App"
yoke qa mission desktop FLAGS windows
yoke qa mission desktop FLAGS focus --process ChatGPT
yoke qa mission desktop FLAGS click --process ChatGPT --name "New chat" --index 1
printf %s 'a short prompt' | yoke qa mission desktop FLAGS type --process ChatGPT --text-stdin
yoke qa mission desktop FLAGS keys --process ChatGPT --keys enter
yoke qa mission desktop FLAGS read --process claude --name "Reply" --control-type Text
yoke test-machine screenshot --test-machine VM
```

Each call runs a Yoke helper as a hidden interactive scheduled task in the
auto-logged-on test user's session. It uses Win32 input and UI Automation, so
it reaches Electron, WinUI and classic apps alike. `windows` lists top-level
windows with handle, title, process, pid, screen bounds and foreground. Every
other action targets one window by `--title` substring, `--process` name or
`--handle`, brings it to the foreground and verifies that before sending input.
`click` takes window-relative `--x/--y` pixels (screenshot pixels minus the
window's bounds) or a UI Automation element selected by exact `--name`,
`--automation-id` and `--control-type`; `--index N` picks one of several
listed matches. `type` reads plain text from stdin only, so it never enters
argv or shell history; send Enter, Tab and shortcuts with `keys`.

Every action, refusals included, prints one JSON object. Typed text appears only as its length, and
text carrying a lease secret or a credential shape is refused
(`desktop_input_secret_refused`) before anything is typed: a password entry is
a human gate. Failures exit 1 with a named code and recovery:
`windows_desktop_locked` (unlock the console over RDP, or release the lease so
the next lease cold-boots and autologon signs in), `windows_window_not_found`,
`windows_window_ambiguous`, `windows_element_not_found`,
`windows_element_ambiguous`, `windows_foreground_refused`,
`windows_foreground_changed`, `windows_click_target_obscured` and
`windows_input_blocked`. An option the action does not use is refused
(`desktop_input_option_unused`), never ignored. Other operating systems refuse
`desktop_input_unsupported_os`: drive macOS apps with `--gui-session`
osascript, and Linux apps with `--gui-session` xdotool.

## Tray startup and autologon

Follow [tray startup and cold-boot checks](windows-native-desktop.md#tray-startup-and-autologon).
