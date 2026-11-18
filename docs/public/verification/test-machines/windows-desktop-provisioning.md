# Windows WSL desktop provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > WSL desktop provisioning
<!-- /yoke:breadcrumbs -->

[Windows WSL host provisioning](windows-host-provisioning.md) owns the ordered
bare-host setup, network, registration and baseline procedure. Complete these
desktop steps at its section 6, then return there to capture and prove the home.

## Desktop and browser coverage

Registered terminal QA uses tmux transcripts. GUI commands and
`yoke test-machine screenshot --test-machine NAME --json` start or
reuse the same WSL XFCE display through the existing Linux desktop helper;
the screenshot captures that display, including its actual headed browser.
Declare the dedicated WSL user as `desktop_user` and its xrdp port as
`desktop_port`; the Windows SSH user remains the account owning the distro.
The capability-owned fixture password is streamed on private stdin. Another
user's ambiguous desktop refuses; no native Windows RDP login is needed.

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
working directory first:

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
port only on the `Tailscale` interface. Its output names the
`tailnet_listener`; `--verify` proves the proxy, the rule and a connection.
Run it from the Windows administrator's SSH session so `netsh` and
`New-NetFirewallRule` can apply. Like the Linux provisioner, it requires `--browser-project` and
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
The product streams its capability-owned desktop secret on private stdin, sets
the dedicated WSL fixture password with `sudo -n chpasswd`. The next retained
GUI-session operation uses the existing uploaded `xrdp-sesrun` helper; no host
harness-package import is needed. No secret enters a file, argv or output. The
operator never types sudo, sets a machine password or logs into either desktop.
Agents authorize the operator identity with `yoke browser authorize
--test-machine` and prove its Chromium renders there before requesting only
personal application sign-in. Success leaves `headed_application_proved=false` until that
independent check. Provisioning starts no session; `--verify` refuses the secret flag.
No auto-logon or public listener change is made.
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
