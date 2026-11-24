# Native Windows desktop and autologon

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows desktop and autologon
<!-- /yoke:breadcrumbs -->

Set up the native lab's interactive console and prove that it signs in
automatically after a cold boot. Start with [native Windows host provisioning](windows-native-host-provisioning.md).

## Desktop and sign-ins

Provisioning validates the stored desktop password against the local lab
account before configuring autologon. A credential rejection gives the
`yoke test-machine secret set --test-machine M --key desktop_password --value-file FILE`
command for importing the account's current password. Provisioning then sets
`AutoAdminLogon`, removes `AutoLogonCount` and stores the lab password in LSA.
It disables locking for the dedicated test desktop. On
a cold boot, Yoke waits up to ten minutes for SSH and Explorer in the lab
account's console session before starting desktop work. An SSH session that
reports `windows_console_session_missing` stays available for repair. Check
the VM console and rerun Windows desktop provisioning. Close the viewer and
run `yoke test-machine verify --test-machine VM` to check Explorer and an
unlocked display in the interactive console.

The warning reports `AutoAdminLogon` (whether automatic sign-in is enabled),
`DefaultUserName` and `DefaultDomainName` (the configured account), and whether
`AutoLogonCount` is present (a counter can limit automatic sign-ins). It also
reports whether the lab account is enabled or locked. If `AutoAdminLogon=0`,
rerun desktop provisioning to validate the stored password and restore autologon.

Follow the [Tailscale and bootstrap RDP guide](windows-native-harnesses.md#first-tailscale-login-and-bootstrap-desktop).
Register RDP on port 3389 for `yokeqa` using `direct` and MagicDNS after tailnet
proof, or `ssh-forward` and `127.0.0.1` during bootstrap. Use
`yoke test-machine desktop-access --view` to reconnect and unlock.

Disconnect without signing out. The administrator-owned `YokeQa-ReturnToConsole`
task returns this account to the console. If it fails, check Task Scheduler's
Last Run Result and confirm the console is free. With the viewer closed, `yoke test-machine screenshot` captures the desktop and
`yoke qa mission desktop` drives its apps.

Continue with [native harness installation and sign-ins](windows-native-harnesses.md)
before capturing goldens.

## Tray startup and autologon

Configure automatic logon using an LSA-protected password (such as Microsoft's
Sysinternals Autologon), never a plaintext Winlogon `DefaultPassword`. Disable locking only for this dedicated test desktop under
the project's lab policy. Cold-start the VM and prove a scheduled task with
`LogonType=Interactive` runs as the standard user without an RDP client open.

A later boot reported SYSTEM `NeedsLogin`, no node key and no expected IP
assignments despite a running Tailscale service. Fresh operator GUI login
restored SYSTEM Running/key/startup-target and the known DNS/IP/private routes.
The selected profile changed from `5967` to `0860`; never hardcode a historical
profile ID as evidence of today's identity. Inspect it privately and compare
the expected node, DNS and addresses before accepting a replacement profile.

The actual MSI startup entry was common Startup `Tailscale.lnk`, targeting the
signed installed `tailscale-ipn.exe` with no arguments. Its tray process started
before the human RDP login. A non-SYSTEM LocalAPI request can select an OS-user
profile, but the precise caller that caused the earlier loss remains unproven.
Do not infer that earlier successful boots lacked autologon.

Provisioning's `Disable-YokeTailnetTrayStartup` checks the exact shortcut,
trusted owner, unlinked ancestors, signed target and empty arguments. It keeps a
byte-verified, content-addressed backup in protected `C:\ProgramData\YokeQa\private`
before removing that exact Startup entry. It refuses unknown Run/user-startup
forms, changed objects or backup collisions; it does not stop the SYSTEM service,
select a profile or edit Tailscale state. Recheck after vendor reinstall/update.

Before acceptance inventory startup entries and tray-process/logon times. Run
two distinct cold boots with automatic `yokeqa` logon demonstrably completed,
tray autostart absent, the same selected identity, nonempty startup key,
SYSTEM Running/key/live adapters, private standard SSH/RDP and public3389 denial.
Use explicit stop/start boundaries for these cold-boot proofs, with no selection
or repair between them. Keep the lab on afterward while the item needs it.
Probe receipts preserve exact allowlisted errors, including NeedsLogin's running
self-identity refusal; unknown/native or secret-bearing errors become a fixed
unclassified failure. Neither classification is a passing readiness receipt.
