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

A human operator can run this command from a plain terminal while a QA session
leases the machine, to observe or assist that session. Access keeps the lease's
owner, heartbeat, and lifetime unchanged. Harness sessions must own the lease
and still receive `test_machine_leased` for another session's machine. The
command names the assisting operator and lease, and records desktop access
authorization as `SessionActionPerformed` in the holder's history with the
actor and lease id. If audit capture is unavailable, the output names the
reason and asks the control-plane operator to repair it; access still proceeds.

The viewer uses the registered Linux or Windows WSL user's XFCE display over
RDP. It measures that display's geometry, supplies the fixture password through
stdin, and owns the SSH forward until the viewer closes. It does not write a
password file or put the password in the client arguments. Personal sign-in is
performed by the operator in the visible desktop.

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

Renderer selection uses SDL's documented [render-driver hint](https://wiki.libsdl.org/SDL3/SDL_HINT_RENDER_DRIVER).
The [FreeRDP SDL update loop](https://github.com/FreeRDP/FreeRDP/blob/3.32.1/client/SDL/SDL3/sdl_freerdp.cpp)
drains pending drawing updates before returning to event processing.
