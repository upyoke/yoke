"""Name a sealed standard probe's failure with the step that fixes it."""

from __future__ import annotations

import json
import re

from yoke_harness.baseline_probe_failure_causes import (
    CHECK_UNMET,
    LAYOUT_UNRECOGNIZED,
    MACHINE_DRIFT,
    PROBE_FAILURE_CAUSES,
    UNDECLARED_EXIT,
    failure_evidence,
)
from yoke_harness.ssh_mac_host_session_state import SCREEN_SAVER_DISABLE_COMMAND

CHECKLIST = ".yoke/docs/verification/test-machines/host-provisioning.md"
#: Saving a sign-in is a recapture: it proves the real requests, quits the apps
#: holding sign-ins and seals a new baseline, so no later reset rolls it back.
SAVE_BASELINE_COMMAND = (
    "yoke test-machine golden-capture --test-machine TEST_MACHINE"
)
RECOVERIES = {
    "Claude real request": "Sign in Claude with claude auth login in the test user's session.",
    "Codex real request": "Sign in Codex with codex login in the test user's session.",
    "Cursor real request": "Sign in Cursor with agent login in the test user's session.",
    "Claude bypass accepted": "Have the operator accept Claude's one-time bypass prompt in the test user's session.",
    "Claude desktop signed in": "Open Claude for Mac in the test user's GUI session. Complete onboarding if prompted, verify the signed-in account in Chat, Code or Cowork, then quit Claude.",
    "macOS login keychain readable": "Use GUI Terminal to unlock/re-key the login keychain after a password change and sign in Claude again; the keychain stays live through resets.",
    "macOS screen saver disabled": f"As the GUI test user run {SCREEN_SAVER_DISABLE_COMMAND} before capture; save a new golden and prove the reset roundtrip.",
    "Linux desktop input available": "Provision xdotool as a baseline package before capture, not as a QA package; capture a new golden and prove the fresh-host reset roundtrip.",
    "machine-baseline": MACHINE_DRIFT.recovery,
}



def _reported_app_version(stdout: str) -> str:
    """Read the app version an unrecognized-layout probe printed, or say why not."""
    try:
        record = json.loads(stdout)
    except ValueError:
        record = None
    version = record.get("app_version") if isinstance(record, dict) else None
    if isinstance(version, str) and re.fullmatch(r"[0-9A-Za-z.\-]{1,40}", version):
        return version
    return "unreadable (check Claude > About Claude)"


def _reported_drift(stdout: str) -> list[str]:
    """The drift names the probe printed; only short identifiers survive."""
    try:
        record = json.loads(stdout)
    except ValueError:
        record = None
    found = record.get("drift") if isinstance(record, dict) else None
    if not isinstance(found, list):
        return ["drift_unreported"]
    return [n for n in found if isinstance(n, str) and re.fullmatch(r"[a-z_]{1,60}", n)][:20]


def standard_probe_failure(
    name: str, exit_code: int, stdout: str = ""
) -> dict[str, str] | None:
    """Name a sealed standard probe's failure from its exit code, or None."""
    step = RECOVERIES.get(name)
    if step is None:
        return None
    failure = PROBE_FAILURE_CAUSES.get(exit_code, UNDECLARED_EXIT)
    # The named step is the fix only when the program ran and reported the
    # state absent; a missing executable or a timeout has its own fix.
    if failure == CHECK_UNMET:
        recovery = (
            f"{step} Follow {CHECKLIST}, then save it at once with "
            f"`{SAVE_BASELINE_COMMAND}`, which proves it and recaptures the baseline."
        )
    else:
        recovery = f"{failure.recovery} See {CHECKLIST}."
    if failure == MACHINE_DRIFT:
        # The reset is the fix; the probe names each drift it found.
        return {**failure_evidence(failure, name), "drift": _reported_drift(stdout)}
    if failure == LAYOUT_UNRECOGNIZED:
        # The defect report needs the app version whose layout went unrecognized.
        version = _reported_app_version(stdout)
        subject = f"{name} (Claude for Mac {version})"
        return {**failure_evidence(failure, subject, recovery), "app_version": version}
    return failure_evidence(failure, name, recovery)
