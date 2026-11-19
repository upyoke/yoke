"""Find every app the test user left open before a reset restores the home.

A reset used to quit only Terminal and System Events, so any other app a run
left open survived the restore. One left Claude for Mac open behind a sheet;
the next reset's Claude desktop probe opened that app, could not quit it, and
every later reset on the host failed until someone quit it by hand.

So the reset lists the test user's foreground apps with ``lsappinfo``, which
reads LaunchServices and needs no Apple Events grant, and quits every one this
module does not keep. It keeps the session's own UI, and the apps the reset
stops itself: identity browsers get a clean SIGTERM that keeps their cookies,
and the self-host teardown stops the container runtime app. It never quits the
app that carries the controller's connection: the reset's SSH runs over the
Tailscale tunnel, so quitting Tailscale cut one reset off from its own host.
Apps are matched by bundle ID, never by display name.

A listing that fails, or that does not show the GUI session at all, refuses:
an unreadable session and an empty one look alike, and skipping the sweep is
what let the leftover app poison every later reset.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_contracts.test_machine_types import HostActionResult

LIST_COMMAND = "/usr/bin/lsappinfo list"
GUI_APP_LIST_FAILED = "test_machine_gui_app_list_failed"
TERMINAL_BUNDLE_ID = "com.apple.Terminal"
# Every GUI session runs the Dock; a listing without it read no session.
SESSION_PROOF_BUNDLE_ID = "com.apple.dock"
# The tailnet client the controller reaches the host through (``*.ts.net``).
# The reset's own SSH runs over this tunnel, so quitting the app cuts the reset
# off from its host and leaves it off the tailnet until someone relaunches
# Tailscale at the console. Standalone and App Store builds.
TRANSPORT_BUNDLE_IDS = frozenset(
    {
        "io.tailscale.ipn.macsys",
        "io.tailscale.ipn.macos",
    }
)
KEPT_BUNDLE_IDS = TRANSPORT_BUNDLE_IDS | frozenset(
    {
        # The session's own UI. Only Finder is normally a foreground app; the
        # agents are listed in case a macOS release changes their type.
        "com.apple.finder",
        "com.apple.dock",
        "com.apple.systemuiserver",
        "com.apple.loginwindow",
        "com.apple.controlcenter",
        "com.apple.notificationcenterui",
        "com.apple.WindowManager",
        "com.apple.Spotlight",
        # Identity browsers: quit with SIGTERM before this sweep and never
        # force-killed (ssh_mac_sign_in_apps).
        "com.google.Chrome",
        "com.google.chrome.for.testing",
        "org.chromium.Chromium",
        # The container runtime app the self-host teardown stops itself.
        "com.docker.docker",
    }
)
_ENTRY = re.compile(r'^\s*\d+\) "(?P<name>.*)" ASN:', re.MULTILINE)
_BUNDLE = re.compile(r'^\s*bundleID="(?P<id>[A-Za-z0-9.\-]+)"', re.MULTILINE)
_PROCESS = re.compile(r'^\s*pid = (?P<pid>\d+)\b.*\btype="(?P<type>[^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class ForegroundApp:
    """One running app as LaunchServices lists it."""

    name: str
    bundle_id: str | None
    pid: int

    @property
    def target(self) -> str:
        """The AppleScript application specifier that asks this app to quit."""
        if self.bundle_id:
            return f'application id "{self.bundle_id}"'
        escaped = self.name.replace("\\", "\\\\").replace('"', '\\"')
        return f'application "{escaped}"'


def _entries(listing: str) -> list[tuple[str, str | None, int, str]]:
    starts = list(_ENTRY.finditer(listing))
    entries = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(listing)
        block = listing[start.end() : end]
        process = _PROCESS.search(block)
        if process is None:
            continue
        bundle = _BUNDLE.search(block)
        entries.append(
            (
                start["name"],
                bundle["id"] if bundle else None,
                int(process["pid"]),
                process["type"],
            )
        )
    return entries


def running_pid(user: str, pid: int) -> str:
    """Exit 0 and print *pid* while *user* runs it, 1 once gone, 2 unreadable."""
    script = (
        f"p=$(/usr/bin/pgrep -u {shlex.quote(user)} .); [ $? -gt 1 ] && exit 2; "
        f"printf '%s\\n' $p | /usr/bin/grep -x {int(pid)}"
    )
    return shlex.join(("/bin/sh", "-c", script))


def list_foreground_apps(
    run, user: str
) -> tuple[list[ForegroundApp], list[str]] | HostActionResult:
    """Return the apps to quit and the kept ones' names, or a named refusal."""
    listed = run(LIST_COMMAND, timeout=20)
    entries = _entries(listed.stdout or "") if listed.returncode == 0 else []
    if not any(bundle == SESSION_PROOF_BUNDLE_ID for _, bundle, _, _ in entries):
        return HostActionResult(
            False,
            {
                "gui_app_list": {
                    "command": LIST_COMMAND,
                    "exit_code": int(listed.returncode),
                    "stderr": bounded_machine_qa_diagnostic(listed.stderr),
                    "session_listed": False,
                },
                "recovery": (
                    f"Yoke could not list the apps {user} has open on the test "
                    "machine, so it cannot quit the ones a previous session "
                    "left behind. Check that SSH to the machine works and that "
                    f"{user} is logged in at its console (the stderr above names "
                    "the failure), then retry the reset."
                ),
            },
            GUI_APP_LIST_FAILED,
        )
    quit, kept = [], []
    for name, bundle, pid, kind in entries:
        if kind != "Foreground":
            continue
        if bundle in KEPT_BUNDLE_IDS:
            kept.append(name)
        else:
            quit.append(ForegroundApp(name, bundle, pid))
    return quit, kept


__all__ = [
    "GUI_APP_LIST_FAILED",
    "KEPT_BUNDLE_IDS",
    "LIST_COMMAND",
    "TERMINAL_BUNDLE_ID",
    "TRANSPORT_BUNDLE_IDS",
    "ForegroundApp",
    "list_foreground_apps",
    "running_pid",
]
