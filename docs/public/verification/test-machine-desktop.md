# Viewing a Test Machine desktop

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Test Machine desktop
<!-- /yoke:breadcrumbs -->

Baseline reset and verification clear test-account-owned Yoke, Playwright,
Chromium and pip run artifacts from system and OS user temporary locations.
The golden directory and its sidecars, browser-profile baseline and restored
home remain protected. Receipts record `temp_cleanup.freed_bytes` and removed
entries. Only the leaseholder can reset the host. A refusal names the machine,
its owning session or plan, and the next step: wait for another holder, or finish
or abort your own mission before resetting. Do not reset an active mission from
an unrelated command.

A Command QA case that operates a host declares `method_config.os` (or OS slots)
and `host_baselines` or `inherit` in its saved plan. The plan acquires any
matching host, queues when every match is busy or unhealthy, and heartbeats its
lease while the local command runs. Nested host operations borrow that owned
active Command plan lease. A Command without an OS declaration has no host
custody; declare one before running its host operations. A missing or expired lease requires fresh admission;
a released lease with an unknown receipt requires inspecting the retained
capture, rather than repeating the operation.

Machine QA chooses the required OS from `method_config.os`, executable steps,
capability requirements, or the OS slots in `method_config.test_machines`.
Instructions never choose a platform: "Do not use linux-lab" does not require
Linux. Cases without these declarations refuse with
`test_machine_platform_undeclared`; set `method_config.os` to `linux`, `macos`,
`windows` or `wsl`, or list OS slots.
`windows` means native Windows and `wsl` a Windows host whose commands run in
WSL2, so a native case never selects a WSL machine or accepts its receipts.
PowerShell and `cmd.exe` steps imply native `windows`; a WSL case declares
`os=wsl`.

Set `method_config.os` for cases that can run on any matching host. Automatic
QA selects only verified, healthy hosts and can use another eligible host while
the first is busy. To require capabilities, add a JSON array such as
`"capability_tags": ["arch:x64", "codex-desktop-signed-in"]` to `method_config`.
Record tags in each host's non-secret settings as comma-separated text, using
Edit settings or `yoke test-machine settings-replace`. Every case tag must be
present on the selected host. A slotted case instead maps each slot OS to its
tags, such as `{"macos":["macos:15"]}`, and they apply to every slot of that OS. Test
Machines of one kind are identical, so a case never names a host: authoring
refuses one with `test_machine_name_forbidden`. Frozen deployment run snapshots were
converted to OS form like other stored cases, so a stage never refuses a case
only because its frozen copy once named a host.

A replacement case starts with no inherited machine preference. A resumed QA
execution keeps the host from its own execution history or continuation chain,
unless the run's `--test-machine` names a different host. Finish or abort an
admitted case that still owns host state before changing its driver.

Simultaneous machine-QA cases get one distinct host per OS slot and drive the
slot marked `driver`; see [host-set authoring](exploration.md#authoring-shape).

When verification marks a host unhealthy, repair the named failure and run
`yoke test-machine verify --test-machine NAME` to wake the waiting line.
Keep the sealed baseline unchanged during this recovery. Run
`yoke test-machine reset --test-machine NAME` for an authorized reset;
read each command's `--help`.

Test Machine reads, operation receipts and desktop routes name the host in
`test_machine`; `yoke test-machine list` returns `test_machines`. A CLI reading
an answer from a server that predates those fields refuses
`test_machine_response_field_missing`: run the Yoke CLI release that server
serves, or update the server.

Mission preparation requires at least 1 GiB free on the home and temporary
filesystems before package setup or scratch creation. A
`test_machine_disk_space_low` refusal records the observed space and minimum;
finish or abort the owning mission, reset the host, and, if reset cannot
recover that space, grow its disk online as the installed Machine QA
`.yoke/docs/verification/test-machines/host-provisioning.md` "Disk sizing and online resize"
section describes before retrying QA. Test Machines need at least 40 GiB.

The named machine's `desktop_password` secret is its administrator password,
used for desktop access and macOS/Linux administrator commands. Run one setup
command with `yoke test-machine exec --test-machine NAME --admin -- COMMAND ARGS...`.
Read its `--help`; product code reads the stored secret, supplies it on private
stdin to sudo, and redacts output. The command receives no stdin. Import the
credential through `yoke test-machine secret set --test-machine NAME --key desktop_password --value-file PASSWORD_FILE`.

Run `yoke test-machine desktop-access --test-machine NAME --view` on the
workstation holding the registered fixture credentials. Read the command's
`--help` for route prerequisites, refusals, and cleanup. The command acquires
an unleased host or borrows your existing lease and starts a stopped cloud
machine before desktop work. Its own lease releases in cleanup, including
failures, and a borrowed lease stays with its caller. Cloud machines stay running
after release. SSH failures report `desktop_transport_unavailable` with the SSH
error; `desktop_user_mismatch` means SSH succeeded as a different user.

A session holding a live steering seat on the machine's project can run this
command while a QA session leases the machine, to observe or assist that
session (`yoke claims steering acquire --project P`). Access keeps the lease's
owner, heartbeat, and lifetime unchanged. Any other session must own the lease
and receives `steering_seat_required` for another session's machine; the
refusal names the seat to acquire. The command names the assisting operator,
seat and lease, and records desktop access authorization as
`SessionActionPerformed` in the holder's history with the actor and lease id. If audit capture is unavailable, the output names the
reason and asks the control-plane operator to repair it; access still proceeds.

The viewer uses the registered Linux or Windows WSL user's XFCE display over
RDP over the registered route: direct to the MagicDNS host on the tailnet, or
the SSH-forward fallback, which it owns until the viewer closes. It measures
that display's geometry, reports `resolution`, and supplies the fixture
password through stdin. A new unattended XFCE desktop starts at 1920×1080.
A reused display below that size is resized when no viewer is connected. The
command refuses with display repair instructions when the minimum is unavailable. It does not write a
password file or put the password in the client arguments. Personal sign-in is
performed by the operator in the visible desktop.

A native Windows Test Machine (`os=windows`) is viewed on its own RDP listener
as the registered `desktop_user`; a `DOMAIN\user` name is passed as FreeRDP's
domain and user. The viewer requests a 1920×1080 desktop and reports
`desktop_session: native` and `resolution: 1920x1080`. Signing in as the
autologon user disconnects the console. When the viewer closes, the host's
`YokeQa-ReturnToConsole` task returns the session to the console. Native
provisioning registers `YokeQa-ConsoleDisplay` to set a usable adapter mode
when the test user signs in or returns to the console. Reset also applies
the minimum. Verify and `yoke qa mission desktop` report the interactive
session resolution and refuse when the fixture cannot provide at least
1920×1080. Configure the VM display adapter to expose that mode before retrying.

A macOS Test Machine's VNC route opens in macOS Screen Sharing instead, from a
Mac workstation. Before opening, Yoke uses the registered SSH key and the
signed-in Mac's Terminal bridge to measure the display. When it is below
1920×1080, Yoke selects the smallest usable display mode that meets the minimum,
keeps it for that login session, and reports the observed resolution. The test host needs the Command Line
Tools and a display adapter with a suitable mode. `--view` opens
`vnc://USER@HOST:PORT` with the user name only,
copies the fixture password to the clipboard through `pbcopy` stdin, and prints
one line asking you to paste it at the Screen Sharing prompt. After 60 seconds
Yoke clears the clipboard if it still holds the password; clipboard-history
apps may keep their own copy. Press Enter in the terminal when done to close
any SSH forward. Another workstation refuses
`desktop_view_requires_mac_workstation`; run without `--view` and connect any
VNC client to the printed address.

For a loopback SSH forward, SSH host-key verification is the trust boundary.
The viewer uses `/cert:ignore`, so random local ports never consult or change
FreeRDP's per-port certificate cache. SSH keeps its existing known-hosts check.

A direct RDP route trusts the host's self-signed certificate on first use. Yoke
completes an RDP TLS handshake, records the certificate's SHA-256 fingerprint
for `HOST:PORT` in `test-machine/rdp_certificates` under the Yoke home, prints
`desktop_certificate_pinned`, and passes FreeRDP
`/cert:fingerprint:sha256:HASH`. Later connections must present the same
certificate. A different one refuses `desktop_certificate_changed` with both
fingerprints; if the host's certificate was deliberately regenerated, delete
that line and retry, otherwise do not connect. Without `--view`, the direct
route prints the pinned `certificate_sha256` for comparison in your own client;
with `--view` the receipt names it too.

Linux and Windows WSL start XFCE and run desktop commands with
`GDK_BACKEND=x11`, keeping GTK on the captured Xorg display even when WSLg
also provides a Wayland socket. Screenshots wait for the desktop's first frame.
A blank capture from a reused desktop restarts the fixture session once through
the normal start path, then waits for its first frame. A connected RDP client
or another login blocks that restart; close it before retrying. A desktop that
stays blank refuses with `screenshot_png_invalid`, session state, and tails of
`~/.xsession-errors` and `/var/log/xrdp-sesman.log` (including read failures).
Repair XFCE/Xorg using those diagnostics, then rerun `yoke test-machine verify`.

Desktop access reports `desktop_session=started`, `reused`, or `restarted`.
A fixture XFCE session older than the running xrdp-sesman service is orphaned:
sesman lost its session registry when it restarted. RDP access ends that stale
fixture desktop, waits for its X socket to disappear, then starts a replacement.
A connected RDP client blocks this repair; close it and rerun desktop access.
GUI commands continue using their existing display without this access repair.

Host-control SSH commands share a per-machine connection on the executing
workstation. Its private socket lives under Yoke's existing scratch roots;
when the configured path is too long for a Unix socket, it uses Yoke's short
OS temporary scratch root. The master expires after 30 idle seconds. A diagnosed stale socket reports
`host_control_ssh_stale_socket`; OpenSSH opens a fresh connection before
remote execution. If it repeats, wait 30 seconds and retry. Other disconnects
are not retried because the remote command may already have run.
`host_control_ssh_socket_unavailable` asks you to configure a short writable
Yoke `temp_root`, then retry the host command.

Only one RDP viewer may connect to a Linux fixture at a time. A second viewer
refuses `linux_desktop_viewer_connected`; close the open `Yoke desktop: NAME`
viewer or let `browser authorize` finish before retrying. GUI commands may reuse
the display while its existing viewer is connected.

Reset asks native Chromium's main process to quit gracefully, allowing it to
flush live sign-ins. Chromium may flatten process arguments in `/proc`; process
discovery still excludes renderer, zygote and crash-handler children. Killing
those children alongside the browser can leave its profile marked crashed.
Keep browser sign-ins live, never golden-capture or wipe them, and require the
fresh request's exact approval tab. An older restored tab is never approval proof.

To sign a browser identity in, run `yoke browser authorize --project P
--identity NAME --test-machine MACHINE` from the connected workstation. It reads
the project's declarations, opens this FreeRDP viewer when the machine has a
Linux, native Windows or Windows WSL RDP route, and opens the authorization window on that
desktop. Close the browser window when done; the viewer closes when
verification finishes. A macOS machine with a VNC route opens in Screen Sharing
the same way as `--view`; quit it after verification finishes. If no viewer
route or client is available, the command prints this desktop-access command
and its recovery, then still waits for sign-in.
No settings JSON or control-plane connection is needed on the Test Machine.
Read `yoke browser authorize --help` and
[browser identities](browser-identities.md) for SSH, lease and
GUI prerequisites.

FreeRDP opens full-screen on the operator's display and uses `/smart-sizing`
to fit the remote desktop to it. Press Ctrl+Alt+Enter to switch to a resizable
window. Resizing only changes the local view. See the
[FreeRDP SDL window setup](https://github.com/FreeRDP/FreeRDP/blob/3.32.1/client/SDL/SDL3/sdl_context.cpp).

On macOS, the FreeRDP SDL client uses OpenGL rendering. Continuous remote updates
can keep its default Metal renderer waiting for drawables inside the update loop,
starving Cocoa input processing. The selection applies only to this child
process; it changes no workstation settings. Linux retains its renderer
selection. FreeRDP remains the viewer on both platforms.

The helper announces `desktop_view_log: PATH` before launching the client. That
private mode-600 file retains FreeRDP INFO output, redacting the fixture password
before writing. Keep it for diagnosis; it remains after success or failure and
is returned as `log_path`. The receipt also preserves `client_exit_code`.

FreeRDP SDL can return 131 after an ordinary window close. The helper treats
131 or 145 as a successful close only when the log proves framebuffer
initialization and local cancellation, with no SDL exception. Other nonzero
exits remain `desktop_view_failed` and name the retained log. A client requiring
a forced kill during cleanup reports `desktop_view_unresponsive`, also with
the log path. Inspect that log, repair the named client or registered desktop
route, and rerun the command. Capture-storage failures refuse explicitly.

`desktop_rdp_client_missing` is the only failure that asks you to install
FreeRDP. Other failures name the logged `ERRCONNECT_*` or `ERRINFO_*` reason:
connection failures point to the registered port and xrdp service; authentication
failures point to the fixture user and secret. `ERRINFO_LOGOFF_BY_USER` means
the remote desktop logged off: inspect `/var/log/xrdp-sesman.log` for a window
manager that exited immediately, repair that session, and rerun the viewer.

Renderer selection uses SDL's documented [render-driver hint](https://wiki.libsdl.org/SDL3/SDL_HINT_RENDER_DRIVER).
The [FreeRDP SDL update loop](https://github.com/FreeRDP/FreeRDP/blob/3.32.1/client/SDL/SDL3/sdl_freerdp.cpp)
drains pending drawing updates before returning to event processing.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
