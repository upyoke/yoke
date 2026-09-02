# Terminal bridge capture: own the window, name the failure, keep the restore

## What broke

`yoke test-machine verify` against a dedicated Mac failed four times in one
afternoon with a single umbrella `error_code`, `terminal_app_control_unavailable`.
The stored `terminal_bridge` check held four booleans — launch true, input true,
transcript true, screenshot false — and nothing else: no command line, no exit
code, no window bounds, no display bounds, no console user. An operator spent
twenty minutes at the physical console ruling out modals, the console user, and
the Screen Recording grant by hand, because the evidence could not distinguish
them.

The cause was window placement, and then two things underneath it. The bridge
captured a screen *region* computed from the driven Terminal window's bounds,
and those bounds came from a 1500-point-wide rectangle compiled into the code.
That rectangle does not fit this machine's 1280-point display, so Terminal
resolved the overflow by sliding the window off the left edge — which is what
the operator kept watching happen, and why resetting Terminal's saved window
position changed nothing. A window outside the display still accepts AppleScript
launch, keystrokes, and transcript reads; only the capture notices, which is why
three checks stayed green while one failed with no explanation.

Placing the window correctly then uncovered the rest: the coordinate space
Terminal places windows in and the one the capture measures in are 3584 points
apart on this machine, and its region capture cannot produce an image for any
rectangle at all.

## What the bridge does now

**Placement derives from the display, not from constants.** The host is asked
for the usable region of its main display (`NSScreen` via JavaScript for
Automation, converted from bottom-left to Terminal's top-left origin), and both
the driven window and the helper window that issues the capture are laid out
inside that region. The helper is placed clear of the captured rectangle rather
than merely sent behind it, because a capture records whatever the window
server composited there. Before each capture the window is un-minimized, its
bounds are set, and the result is read back; a window that still lands outside
the region is re-anchored once, and a window that will not come inside fails
with a named code instead of capturing nothing. Placement handles position and
minimized state but not Spaces: every window this path captures is opened by the
same run, so it is already on the Space that was current, and a future path that
captured a window it did not create would have to establish that itself.

**The geometry question is asked from inside Terminal.app**, for the same
reason the capture is: screen geometry is a window-server fact, and that is the
session whose windows get placed and whose pixels get captured. This host
answered the same over the transport, so it is a consistency choice rather than
a fix for an observed difference — but a process outside the graphical session
can be answered for a desktop it is not part of, and every rectangle in this
path is computed from that answer.

**The display's coordinate origin is not the desktop's.** Window bounds live in
NSScreen's global space, and the Mac this was diagnosed on reports its only
1280x1024 screen at global x=3584. Both consequences bit. The compiled-in
1500-point-wide rectangle did not fit that 1280-point display at all, and
Terminal resolved the overflow by sliding the window off the left edge — what
the operator kept seeing. And a rectangle written as if the display began at
the origin lands nowhere near it: the capture reported that a rectangle at
x=40 "does not intersect any displays" while the same size at x=3624 did.

**The capture takes the whole display and crops.** `screencapture -R` produces no
image on that Mac for *any* rectangle that intersects the display — tested down
to 100x100 — while the whole-display form succeeds on the same host in the same
second. So the bridge captures the display and crops to the window with `sips`.
That crop is what needs the second coordinate: a whole-display image's own
top-left pixel is the display's corner, so the host reports both the usable
region for placement and that corner in the same space, and a placed rectangle
is converted into image pixels — times the backing scale factor — before it is
cropped. The artifact is still exactly the window, and the path no longer
depends on a region form that is not reliable across supported macOS versions.

**Every capture failure names its class and its recovery.** The screenshot leg
records the capture command line, its exit code and stderr (it runs through the
Terminal.app command runner, so both survive), the window id and bounds it
targeted, the display's visible frame and size, the console user, and whether the
display is locked. `terminal_app_control_unavailable` remains only for the
launch, input, and transcript legs, where Terminal.app control genuinely is
unavailable. A capture failure reports one of
`terminal_window_off_screen`, `terminal_console_user_mismatch`,
`terminal_display_locked`, `terminal_display_frame_unavailable`,
`terminal_screen_capture_failed`, or the pre-existing
`terminal_screen_recording_required`, each paired with the operator step that
clears it. Those diagnostics are what identified both coordinate-space bugs
above on their first run against the live machine, from the recorded command,
its stderr, the window bounds, and the display frame side by side.

## Why a capture failure no longer skips the host baselines

The verification contract runs two checks and then two host baselines, and the
old sequence stopped at the first failure of any step. So a screenshot problem
also skipped the `fresh-host` restore, and a self-host walk's residue — a
cleartext admin token under `/tmp`, a client token under `~/.yoke/secrets`, a
dead connection — stayed on the machine for as long as the screenshot problem
took to diagnose. The machine was left dirtier by the diagnosis than by the
failure.

Three options were on the table: reorder so the restore runs before the bridge
check, degrade a capture failure to a warning, or record the failure and keep
going. The third is what shipped.

Reordering would have made the contract's `checks`-then-`baselines` shape a lie
and given no principle for the next step added to either list. Degrading to a
warning would have let a machine report `verified` while it could not produce a
screenshot, which is exactly the honesty the verified status exists to carry.

So the sequence now distinguishes a precondition from a capability. The first
check proves the transport; nothing later can run without it, and its failure
still ends the run. A later failure is recorded, sets the reported `error_code`,
and the sequence continues into the baselines — the machine still gets restored,
and the verdict still says `error` with the capture class that caused it. The
server-side submission validator enforces exactly that shape: an error result
must name its first failed step, and only a failed transport check may end the
sequence early.
