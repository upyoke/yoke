# Viewing a Test Machine desktop

Baseline reset and verification clear test-account-owned Yoke, Playwright,
Chromium and pip run artifacts from system and OS user temporary locations.
The golden directory and its sidecars, browser-profile baseline and restored
home remain protected. Receipts record `temp_cleanup.freed_bytes` and removed
entries. Reset/verify refuse `test_machine_cleanup_live_lease` while a mission
owns the host: finish or abort that mission first. Run
`yoke test-machine reset --project P --machine NAME`; read its `--help`.

Mission preparation requires at least 1 GiB free on the home and temporary
filesystems before package setup or scratch creation. A
`test_machine_disk_space_low` refusal records the observed space and minimum;
finish or abort the owning mission, reset the host, and expand its disk if
reset cannot recover that space before retrying QA.

The named machine's `desktop_password` secret is its administrator password,
used for desktop access and macOS/Linux administrator commands. Run one setup
command with `yoke test-machine exec --project P --machine NAME --admin -- COMMAND ARGS...`.
Read its `--help`; product code reads the stored secret, supplies it on private
stdin to sudo, and redacts output. The command receives no stdin. Import the
credential through `yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE`.

Run `yoke test-machine desktop-access --project P --machine NAME --view` on the
workstation holding the registered fixture credentials. Read the command's
`--help` for route prerequisites, refusals, and cleanup.

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
RDP. It measures that display's geometry, supplies the fixture password through
stdin, and owns the SSH forward until the viewer closes. It does not write a
password file or put the password in the client arguments. Personal sign-in is
performed by the operator in the visible desktop.

For a loopback SSH forward, SSH host-key verification is the trust boundary.
The viewer uses `/cert:ignore`, so random local ports never consult or change
FreeRDP's per-port certificate cache. SSH keeps its existing known-hosts check;
direct RDP routes retain certificate verification.

Desktop access reports `desktop_session=started`, `reused`, or `restarted`.
A fixture XFCE session older than the running xrdp-sesman service is orphaned:
sesman lost its session registry when it restarted. RDP access ends that stale
fixture desktop, waits for its X socket to disappear, then starts a replacement.
A connected RDP client blocks this repair; close it and rerun desktop access.
GUI commands continue using their existing display without this access repair.

To sign a browser identity in, run `yoke browser authorize --project P
--identity NAME --machine MACHINE` from the connected workstation. It reads
the project's declarations, opens this FreeRDP viewer when the machine has a
Linux or Windows WSL RDP route, and opens the authorization window on that
desktop. Close the browser window when done; the viewer closes when
verification finishes. If no viewer route or FreeRDP client is available, the
command prints this desktop-access command and its recovery, then still waits
for sign-in. macOS Screen Sharing uses the printed command without `--view`.
No settings JSON or control-plane connection is needed on the Test Machine.
Read `yoke browser authorize --help` and
[browser identities](qa-platform/browser-identities.md) for SSH, lease and
GUI prerequisites.

The resizable viewer scales the shared desktop to fit its window. The initial
window fits within 1280 by 800 logical pixels, with a doubled framebuffer on
macOS for Retina readability. Resizing the window changes only the local view;
the measured remote XFCE geometry stays unchanged. FreeRDP SDL uses the
`/smart-sizing` dimensions for the remote desktop and `/size` for the initial
local window; see its [window setup](https://github.com/FreeRDP/FreeRDP/blob/3.32.1/client/SDL/SDL3/sdl_context.cpp).

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
