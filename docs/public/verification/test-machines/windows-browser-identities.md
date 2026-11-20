# Native Windows browser identities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows browser identities
<!-- /yoke:breadcrumbs -->

For WSL, follow [WSL browser identities](windows-wsl-browser-identities.md).

Return to [native Windows provisioning](windows-native-host-provisioning.md).
These identities belong to the standard Windows test user and its native
headed Chromium. WSL browser profiles are separate and prove no native sign-in.

The first authorization creates `%USERPROFILE%\.yoke-browser-identities`,
restricted to the test user and Administrators/SYSTEM, outside `.yoke`. The
native profile reset preserves this **live** identity store; golden capture
excludes it. Restoring a copy of rotated cookies is not a valid way to
preserve a sign-in.

Declare each project identity, its per-site sign-in checks and the project's
`default_identity` (the operator identity) in the `browser-control`
capability; see [browser identities](browser-identities.md).

## Sign in once per identity

From the operator workstation, after a reset and candidate install:

```text
yoke browser authorize --project P --identity NAME --test-machine windows-native-lab
```

Read `--help`. The command checks declared sites and opens sign-in on the
test user's desktop only for expired ones. It reaches that desktop through the
same native SSH transport Machine QA uses, so the workstation needs the lab's
SSH key imported (`yoke test-machine secret set --test-machine
windows-native-lab --key ssh_private_key --value-file FILE`); without it the
command refuses `desktop_ssh_key_missing`. Agents drive setup and navigation;
Ben enters his own password or credential. No automated browser runs while
authorization owns the profile. Keep cookies and profile contents on the VM,
outside evidence.

## Supply declarations from PowerShell

If the Windows host cannot read the project's declarations, retrieve
`result.settings_json` on a connected machine with
`yoke projects capability-settings get --project P --cap-type browser-control --json`.
Put the JSON document in `$json` on the Windows host, then run:

```powershell
$json | Out-File -Encoding utf8 d.json
yoke browser verify --project P --identity NAME --declarations-json '@d.json'
```

PowerShell can drop inner quotes from inline JSON when calling `yoke.cmd`.
Use `@FILE` with local `browser verify` and `browser authorize`. The file can
include the UTF-8 BOM written by Windows PowerShell 5.1. Quote the whole
`@FILE` argument in PowerShell, including any spaces in the path.

## One login for every page

The identity profiles are the machine's only login store. Every browser page
Machine QA shows on native Windows opens in them, signed in:

- **Installer approval.** A recipe whose step is a `machine_browser_approval`
  gate starts the installer in the interactive desktop with
  `$env:BROWSER='yoke.cmd browser open --project P --identity NAME %s'`, the
  resolved Yoke's folder first on `Path`, and `YOKE_MACHINE_HOME` cleared, so
  the launcher reads the test user's own store. The approval driver then runs
  `yoke browser devtools` over SSH with the Python named in the installer's
  `yoke.cmd` shim; DevTools listens on loopback, so nothing is forwarded.
- **Desktop mission page.** A mission's `yoke browser open` host command starts
  in the test user's desktop through a scheduled task, never SSH session zero.
- **Managed step.** `yoke qa browser setup`, `step` and `stop` host commands
  start there the same way and copy the identity's sign-in state.

An expired login lands the approval tab on the sign-in page; the gate refuses
`machine_browser_sign_in_required` and names
`yoke browser authorize --project P --identity NAME --test-machine windows-native-lab`.
A missing or rewritten `yoke.cmd` refuses `windows_yoke_shim_unreadable`:
reinstall Yoke on the test machine. Admission gates refuse
`native_windows_admission_gate_unsupported`; run them on Linux or macOS.

Newly refreshed sessions stay in the live store whether QA passes, fails or is
interrupted, and a second reset keeps them. Never export a personal host
browser profile or silently substitute a WSL profile.
