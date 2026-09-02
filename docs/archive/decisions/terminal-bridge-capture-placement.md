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

The cause was window placement. The bridge captured a screen *region* computed
from the driven Terminal window's bounds, and those bounds came from a fixed
rectangle compiled into the code. A window whose rectangle falls outside the
display's visible frame still accepts AppleScript launch, keystrokes, and
transcript reads — only the region capture comes back empty or unchanged.
Resetting Terminal's saved window position did not fix it: the coordinates
themselves were wrong for that display, so every run placed the window in the
same off-screen spot.

## What the bridge does now

**Placement derives from the display, not from constants.** The host is asked
for the visible frame of its menu-bar display (`NSScreen` via JavaScript for
Automation, converted from bottom-left to Terminal's top-left origin), and both
the driven window and the helper window that issues the capture are laid out
inside that frame. The helper is placed clear of the captured rectangle rather
than merely sent behind it, because a region capture records whatever the window
server composited there. Before each capture the window is un-minimized, its
bounds are set, and the result is read back; a window that still lands outside
the frame is re-anchored once, and a window that will not come inside fails with
a named code instead of capturing nothing.

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
clears it.

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
