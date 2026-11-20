# Windows WSL desktop provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > WSL desktop provisioning
<!-- /yoke:breadcrumbs -->

[Windows WSL host provisioning](windows-host-provisioning.md) owns the ordered
bare-host setup, network, registration and baseline procedure. Complete these
desktop steps at its section 6, then return there to capture and prove the home.

## Desktop and browser coverage

The lab has two desktops. The Windows account that owns the distro signs in
automatically at the Windows console. Its interactive task can launch WSL
commands whose windows open on Windows, such as a Windows browser opened by
`yoke ui up` inside WSL. The WSL user has its own XFCE/xrdp desktop for Linux
apps, browser identities and tmux terminal QA.

Set `wsl_desktop_session=windows` on the test machine to run
`yoke qa mission host-command --gui-session` in Windows, drive their windows
with `yoke qa mission desktop` on native Windows hosts
([driving desktop apps](windows-native-harnesses.md#driving-desktop-apps)),
and capture that display with mission screenshots or `yoke test-machine screenshot`.
Select `xfce` to route those operations to the Linux desktop. Existing
registrations use XFCE until they declare a selection. Keep `desktop_user`
and `desktop_port` pointed at XFCE for Linux browser sign-ins.

For a requested, announced personal application sign-in handoff, run:

```text
yoke test-machine desktop-access --test-machine NAME --view
```

Read `--help`. Install FreeRDP's visible SDL client on the executing workstation
(macOS: `brew install freerdp`; Linux: the distribution's `freerdp-sdl` package).
The product opens the declared route (direct over the tailnet, or the SSH
forward fallback) and supplies the fixture credential on stdin,
with the existing XFCE dimensions and color depth so xrdp reconnects that display.
It creates no password file. Close the viewer or interrupt the retained command
to close any forward. The user types only their own password or credential.
Tests use agent captures; human viewing is never a test acceptance check.
A connected viewer counts as human adoption: baseline reset/capture must wait
until it closes, even when automation originally started XFCE.

For the selected Server route, reuse Yoke's Linux XFCE/xrdp provisioner
inside WSL with a separate loopback port. The executing operation runs its
stdlib-only helper in the dedicated Linux user's home. Copy
`linux_desktop_listener.py`, `provision_linux_desktop.py` and
`provision_windows_wsl_desktop.py` from the controller's `yoke_harness/host_provisioning/` package directory into that
working directory. Copy `autologon.py`, `console_setup.py` and `stdin_frame.py`
from the package's `native_windows/` directory into the same working directory:

```text
python3 provision_windows_wsl_desktop.py --desktop-password-stdin --browser-project P --browser-identity NAME
python3 provision_windows_wsl_desktop.py --verify
```

The wrapper requires Ubuntu24.04, non-root passwordless sudo, WSL2/systemd and
Windows interop, with WSL3.0.1 or newer (the verified configuration support floor).
It records actual Windows edition/build and WSL version,
installs the existing Linux desktop packages and proves loopback/localhost
access. xrdp stays on WSL loopback; on the Windows host the wrapper adds one
port proxy from the host's Tailscale IPv4 address to `127.0.0.1` on the same
port and one inbound firewall rule, `YokeWslDesktopTailnet`, admitting that
port only on the `Tailscale` interface. The proxy binds only while that
address exists, and Windows starts IP Helper before Tailscale at boot, so the
wrapper also registers the SYSTEM startup task `YokeWslDesktopTailnet`. The task
waits for the Tailscale address and, if the proxy is not listening there,
deletes and re-adds the proxy rule so IP Helper binds it. It never restarts IP
Helper: Tailscale depends on that service, so a restart drops the address. Its output names the `tailnet_listener`; `--verify` proves the
proxy, the rule, the task and a connection. If a connection fails after a
reboot, run `Start-ScheduledTask YokeWslDesktopTailnet` as administrator.
Run it from the Windows administrator's SSH session so `netsh`,
`New-NetFirewallRule` and `Register-ScheduledTask` can apply. Like the Linux provisioner, it requires `--browser-project` and
`--browser-identity` naming the operator identity (the project's
browser-control `default_identity`). It installs the XFCE helpers and selects
`xfce4-terminal` and the Yoke identity launcher as XFCE defaults. The launcher
also handles HTTP, HTTPS, and HTML via the MIME defaults, so `xdg-open` and the
[browser approval gates](linux-browser-identities.md#browser-approval-gates)
land in that identity's profile. `--verify` takes neither flag and refuses
`linux_desktop_default_browser_not_selected` if the browser helper or MIME
selection is missing. In the WSL XFCE session, confirm `exo-open --launch
TerminalEmulator` opens a terminal and `xdg-open https://example.com` opens
the page in the identity browser.
Stream the existing `desktop_password` for the Windows SSH account on private
stdin. The provisioner stores it in Windows LSA for autologon and sets the
dedicated WSL fixture password through `sudo -n chpasswd`. It disables
screen-saver and workstation locking for the Windows lab account and installs
the fixed `YokeQa-ReturnToConsole` task. The task moves that account's disconnected
RDP session back to the console. Reboot the Windows host once after provisioning.

Update [capability tags](host-provisioning.md#register-capability-tags) when desktop sign-ins change.
Run `yoke test-machine verify --test-machine NAME` after reboot,
with the viewer closed. The console probe checks that an interactive scheduled
task shares Explorer's nonzero console session, can read the unlocked display,
and can start the default WSL distro. After a reset, repeat verification to
prove the Windows console survived the Linux home restore.

A locked console makes `yoke qa mission desktop` refuse
`windows_desktop_locked`. To recover a locked Windows console, reboot the
host so autologon signs the account in, or connect to the Windows account over
the lab's private RDP route and unlock it. Disconnect without signing out, then
verify again. If the task fails, inspect its result in Task Scheduler and
rerun provisioning. For XFCE, continue to authorize the operator identity with
`yoke browser authorize --test-machine` and prove Chromium renders there.
The helper reports `headed_application_proved=false` until independent QA.
The provisioner also owns persistent distro setup: it sets only
`[general] instanceIdleTimeout=-1` in the registered Windows user's `.wslconfig`,
preserving other keys and comments. This applies to that Windows user's WSL2
distros. A changed configuration reports `restart_required=true`; save work and
restart WSL before claiming it is applied. `--verify` checks the stored setting,
not its activation or desktop persistence. Prove XFCE and candidate Chromium
survive a gap longer than both default timers without a foreground keeper.
[Microsoft's settings reference](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
distinguishes distro idle shutdown (15000ms) from VM idle shutdown (60000ms).
Systemd services alone do not keep WSL alive; no per-execution sleep is required.
[Microsoft documents localhost access to WSL services](https://learn.microsoft.com/en-us/windows/wsl/networking)
and [systemd prerequisites](https://learn.microsoft.com/en-us/windows/wsl/systemd).
WSLg is a separate route: its [documented GUI prerequisites](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)
name Windows10/11. A version string alone proves no Server GUI support.

### Live browser identities inside WSL

Follow [WSL browser identities](windows-browser-identities.md) before saving.
