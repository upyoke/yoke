"""What the Terminal bridge can fail at, and what a person changes to fix it.

The bridge is the only path to a macOS host's logged-in GUI session, so every
capability it offers -- launching a window, focusing it, typing into it,
reading its transcript, capturing its pixels -- can fail for a reason that
lives on the host rather than in the code: a privacy grant nobody clicked, a
console owned by another login, a locked screen, a setting that blocks
synthetic keystrokes, or simply a machine loaded enough that a window is not
frontmost yet when the keys arrive.

One umbrella error code for all of that sent an operator to the console to
rule the causes out by hand. So each condition is named, and each name carries
the sentence describing what to change. The vocabulary is shared by the
verification check, which reports the first failure, and by the diagnosis,
which runs every capability one at a time and reports all of them.
"""

from __future__ import annotations


# The generic outcome: a bridge capability did not work and nothing narrower
# was observed. Diagnosis exists so this stays rare.
TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE = "terminal_app_control_unavailable"

# A Terminal.app screenshot check that captured identical frames across a
# proven display change: the host lacks the macOS Screen Recording grant for
# Terminal.app, so captures hold wallpaper, not windows.
TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE = "terminal_screen_recording_required"
# The remaining ways a region capture of a driven Terminal.app window fails.
TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE = "terminal_window_off_screen"
TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE = "terminal_console_user_mismatch"
TERMINAL_DISPLAY_LOCKED_ERROR_CODE = "terminal_display_locked"
TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE = "terminal_display_frame_unavailable"
TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE = "terminal_screen_capture_failed"

# The control surfaces the bridge drives before it can capture anything.
TERMINAL_SSH_UNAVAILABLE_ERROR_CODE = "terminal_ssh_unavailable"
TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE = "terminal_system_events_unavailable"
TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE = "terminal_automation_unavailable"
TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE = "terminal_secure_keyboard_entry_on"
# A command run inside Terminal.app could not drive System Events: Terminal
# lacks that Automation grant, so the Safari approval helper and GUI-session
# commands would block on consent until their own timeout.
TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE = (
    "terminal_system_events_automation_missing"
)
# The same probe ran out of time without a denial. A timeout is not evidence of
# a missing grant: a consent prompt nobody answered and a Terminal too loaded to
# start the command both look like this, so it carries its own name.
TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE = (
    "terminal_system_events_automation_timeout"
)
# The probe timed out while Terminal held more windows than any run leaves
# behind. Every GUI-session command opens a window; once hundreds accumulate,
# each new command stalls behind them, whatever the grants say.
TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE = "terminal_window_accumulation"
# The probe failed with neither a denial nor a timeout.
TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE = (
    "terminal_system_events_automation_failed"
)
# A probe that times out while Terminal holds more windows than this is named
# an accumulation. A healthy host holds the one window Terminal opens at launch
# plus one per bridge command in flight.
TERMINAL_WINDOW_ACCUMULATION_THRESHOLD = 10
# The window opened but never became the frontmost one inside the wait, so the
# keys that follow would land in whatever window is frontmost instead.
TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE = "terminal_window_focus_timeout"
TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE = "terminal_keystroke_undelivered"
# Keys were delivered and the expected text never appeared in the window.
TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE = "terminal_transcript_timeout"

TERMINAL_BRIDGE_RECOVERY = {
    TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE: (
        "run `yoke test-machine bridge-diagnose` against this machine; it "
        "exercises each bridge capability on its own and names the host "
        "condition behind this one"
    ),
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE: (
        "grant Terminal.app access under System Settings > Privacy & Security "
        "> Screen & System Audio Recording on the host, then re-run the "
        "verification"
    ),
    TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE: (
        "the driven window would not stay inside the display's visible frame; "
        "confirm the host's display resolution and that no display "
        "arrangement places windows off the menu-bar screen, then re-run the "
        "verification"
    ),
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE: (
        "log the host's graphical session in as the automation user; a "
        "different console user owns the window server and Terminal.app "
        "cannot draw into it"
    ),
    TERMINAL_DISPLAY_LOCKED_ERROR_CODE: (
        "unlock the host's screen and disable its screen saver and display "
        "sleep, then re-run the verification"
    ),
    TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE: (
        "confirm the Mac has an attached or virtual display and an active "
        "graphical login session, then re-run the verification"
    ),
    TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE: (
        "read the recorded screencapture command, exit code, and stderr in "
        "the check evidence and clear the named condition on the host"
    ),
    TERMINAL_SSH_UNAVAILABLE_ERROR_CODE: (
        "confirm Remote Login is on for the automation user and that the "
        "machine running this command holds the test-machine ssh_private_key "
        "capability secret"
    ),
    TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE: (
        "grant the Remote Login helper /usr/libexec/sshd-keygen-wrapper "
        "Accessibility, and Automation for System Events, under System "
        "Settings > Privacy & Security on the host; -25211 names the "
        "Accessibility grant and -1743 the Automation one"
    ),
    TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE: (
        "grant the Remote Login helper /usr/libexec/sshd-keygen-wrapper "
        "Automation for Terminal under System Settings > Privacy & Security "
        "on the host; -1743 names that grant"
    ),
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE: (
        "automation_missing:Terminal->System Events: tick Terminal's System "
        "Events row under Privacy & Security > Automation on the host (older "
        "macOS opens System Preferences instead of asking); if Terminal has no "
        'row there, run `osascript -e \'tell application "System Events" to '
        "count processes'` in Terminal at the console and allow the prompt, "
        "then re-run `yoke test-machine bridge-diagnose`"
    ),
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE: (
        "a command inside Terminal did not finish inside the probe wait and "
        "macOS did not deny it; at the host console, answer any Terminal "
        "consent prompt or terminate-processes sheet, read the recorded load "
        "average, then re-run `yoke test-machine bridge-diagnose`"
    ),
    TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE: (
        "Terminal holds the windows earlier runs left open, and commands "
        "inside it stall behind them; run `yoke test-machine reset`, which "
        "quits and relaunches Terminal, or quit Terminal at the host console, "
        "then re-run `yoke test-machine bridge-diagnose`"
    ),
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE: (
        "read the recorded osascript output in the check evidence and clear "
        "the condition it names on the host, then re-run "
        "`yoke test-machine bridge-diagnose`"
    ),
    TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE: (
        "turn Secure Keyboard Entry off in Terminal's menu on the host; while "
        "it is on macOS discards every synthetic keystroke the bridge sends"
    ),
    TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE: (
        "the driven window never became frontmost inside the focus wait, so "
        "keystrokes would have landed in another window; close what is "
        "holding focus on the host, or reduce its load -- the check evidence "
        "records the load average and the wait it allowed"
    ),
    TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE: (
        "AppleEvents reached the host but the keystroke was refused; check "
        "the Accessibility grant for /usr/libexec/sshd-keygen-wrapper and "
        "that Secure Keyboard Entry is off in Terminal"
    ),
    TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE: (
        "the keystrokes were delivered and the window never showed them "
        "inside the transcript wait; the check evidence records the load "
        "average and the wait it allowed, which scales with that load"
    ),
}

# Every capability the diagnosis exercises, in the order it exercises them:
# each one is a precondition for the next, so a failure names the earliest
# condition rather than every consequence of it.
TERMINAL_BRIDGE_CHECKS = (
    "ssh_transport",
    "console_session",
    "system_events_control",
    "terminal_app_control",
    "secure_keyboard_entry",
    "terminal_system_events_automation",
    "display_frame",
    "window_launch",
    "window_focus",
    "keystroke_delivery",
    "window_transcript",
    "window_screen_capture",
)


def terminal_bridge_recovery(error_code: str) -> str:
    """Return the sentence naming what to change, or refuse an unknown code."""
    try:
        return TERMINAL_BRIDGE_RECOVERY[error_code]
    except KeyError:
        raise ValueError(f"unknown terminal-bridge error code {error_code!r}") from None


__all__ = [
    "TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE",
    "TERMINAL_AUTOMATION_UNAVAILABLE_ERROR_CODE",
    "TERMINAL_BRIDGE_CHECKS",
    "TERMINAL_BRIDGE_RECOVERY",
    "TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE",
    "TERMINAL_DISPLAY_FRAME_UNAVAILABLE_ERROR_CODE",
    "TERMINAL_DISPLAY_LOCKED_ERROR_CODE",
    "TERMINAL_KEYSTROKE_UNDELIVERED_ERROR_CODE",
    "TERMINAL_SCREEN_CAPTURE_FAILED_ERROR_CODE",
    "TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE",
    "TERMINAL_SECURE_KEYBOARD_ENTRY_ON_ERROR_CODE",
    "TERMINAL_SSH_UNAVAILABLE_ERROR_CODE",
    "TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE",
    "TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE",
    "TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE",
    "TERMINAL_SYSTEM_EVENTS_UNAVAILABLE_ERROR_CODE",
    "TERMINAL_TRANSCRIPT_TIMEOUT_ERROR_CODE",
    "TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE",
    "TERMINAL_WINDOW_ACCUMULATION_THRESHOLD",
    "TERMINAL_WINDOW_FOCUS_TIMEOUT_ERROR_CODE",
    "TERMINAL_WINDOW_OFF_SCREEN_ERROR_CODE",
    "terminal_bridge_recovery",
]
