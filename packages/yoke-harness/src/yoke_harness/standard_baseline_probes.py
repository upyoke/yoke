"""Mandatory capture probes, sealed through the existing baseline document."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from yoke_harness import baseline_harness_requests, baseline_native_failures
from yoke_harness.baseline_probe_failure_causes import (
    CHECK_UNMET,
    PROBE_EXIT_CODES,
    PROBE_FAILURE_CAUSES,
    UNDECLARED_EXIT,
    failure_evidence,
)
from yoke_harness.ssh_mac_host_session_state import (
    SCREEN_SAVER_DISABLE_COMMAND,
    SCREEN_SAVER_READ_COMMAND,
)
from yoke_harness.test_machine_types import HostActionResult

CHECKLIST = "docs/packs/machine-qa/host-provisioning.md"
#: Saving a sign-in is a recapture: it proves the real requests, quits the apps
#: holding sign-ins and seals a new baseline, so no later reset rolls it back.
SAVE_BASELINE_COMMAND = (
    "yoke test-machine golden-capture --project PROJECT --machine MACHINE"
)
RECOVERIES = {
    "Claude real request": "Sign in Claude with claude auth login in the test user's session.",
    "Codex real request": "Sign in Codex with codex login in the test user's session.",
    "Cursor real request": "Sign in Cursor with agent login in the test user's session.",
    "Claude bypass accepted": "Have the operator accept Claude's one-time bypass prompt in the test user's session.",
    "macOS login keychain readable": "Use GUI Terminal to unlock/re-key the login keychain after a password change and sign in Claude again; the keychain stays live through resets.",
    "macOS screen saver disabled": f"As the GUI test user run {SCREEN_SAVER_DISABLE_COMMAND} before capture; save a new golden and prove the reset roundtrip.",
    "Linux desktop input available": "Provision xdotool as a baseline package before capture, not as a QA package; capture a new golden and prove the fresh-host reset roundtrip.",
}


# Each sealed program exits with a code from the one cause table. The future
# import leads, because a program embedding module source must hoist it.
_FUTURE = "from __future__ import annotations\n"
_PREAMBLE = f"{_FUTURE}EXIT = {PROBE_EXIT_CODES!r}\n"


def standard_probe_failure(name: str, exit_code: int) -> dict[str, str] | None:
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
    return failure_evidence(failure, name, recovery)


def _probe(name: str, program: str) -> dict:
    return {"name": name, "argv": ["/usr/bin/python3", "-c", _PREAMBLE + program]}


def standard_probes(os_name: str) -> list[dict]:
    """Run harnesses without tools; only an exit code and a sanitized rejection leave the host."""
    if os_name not in {"macos", "linux", "windows"}:
        raise ValueError("baseline_probe_os_unsupported")
    source = (
        Path(baseline_harness_requests.__file__)
        .read_text(encoding="utf-8")
        .replace(_FUTURE, "", 1)
    )
    native_source = (
        Path(baseline_native_failures.__file__)
        .read_text(encoding="utf-8")
        .replace(_FUTURE, "", 1)
    )
    source = (
        native_source
        + "\n"
        + source.replace(
            "from yoke_harness.baseline_native_failures import NATIVE_FAILURES, native_failure_cause",
            "",
        )
    )
    probes = []
    for name, executables in (
        ("Claude", ("claude",)),
        ("Codex", ("codex",)),
        ("Cursor", ("agent", "cursor-agent")),
    ):
        # The sealed program carries the existing response parser, so remote
        # machines need no Yoke installation. Native output stays on the host.
        program = (
            source
            + "\n"
            + f"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
search = os.pathsep.join([str(Path.home() / '.local/bin'), os.environ.get('PATH', '')])
executable = next((p for x in {executables!r} if (p := shutil.which(x, path=search))), None)
if not executable: sys.exit(EXIT['probe_executable_missing'])
request = harness_request([executable])
deadline = time.monotonic() + 110
def attempt(limit=None):
    remaining = deadline - time.monotonic()
    if request.name == 'Cursor' and remaining <= 0:
        sys.exit(EXIT['probe_request_timed_out'])
    timeout = min(limit, remaining) if limit is not None else max(1, remaining)
    try:
        return subprocess.run(request.argv, cwd=REQUEST_WORKSPACE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if request.name == 'Cursor':
            print(json.dumps(request.timeout_rejection(exc.stdout)))
            return None
        sys.exit(EXIT['probe_request_timed_out'])
    except OSError:
        sys.exit(EXIT['probe_launch_failed'])
result = attempt(50 if request.name == 'Cursor' else None)
# One Cursor retry shares the original deadline, whether a stall or a tool
# call consumed the first attempt. Other harnesses retain one full attempt.
if result is None or (result.returncode == 0 and request.only_tool_call_rejected(result.stdout)):
    result = attempt(deadline - time.monotonic())
if result is None:
    sys.exit(EXIT['probe_request_timed_out'])
if result.returncode != 0:
    refusal = request.native_refusal(result.stdout, result.stderr)
    rejection = request.reply_rejection(result.stdout, exit_code=result.returncode)
    if rejection is not None:
        print(json.dumps({{**rejection, 'harness_exit_code': result.returncode}}))
    sys.exit(EXIT[refusal['cause'] if refusal else 'probe_harness_exit_nonzero'])
rejection = request.reply_rejection(result.stdout)
if rejection is None: sys.exit(0)
# Only the sanitized rejection record leaves the host; the reply stays here.
print(json.dumps({{**rejection, 'harness_exit_code': result.returncode}}))
sys.exit(EXIT['probe_reply_unanswered'])
"""
        )
        probes.append(_probe(f"{name} real request", program))
    probes.append(
        _probe(
            "Claude bypass accepted",
            """
import json, os, pathlib, sys
root = pathlib.Path(os.environ.get('CLAUDE_CONFIG_DIR', str(pathlib.Path.home() / '.claude')))
try:
    settings = json.loads((root / 'settings.json').read_text())
    ok = settings.get('skipDangerousModePermissionPrompt') is True
except (OSError, ValueError, AttributeError):
    ok = False
sys.exit(0 if ok else EXIT['probe_check_unmet'])
""",
        )
    )
    if os_name == "macos":
        saver_argv = shlex.split("/usr/bin/" + SCREEN_SAVER_READ_COMMAND)
        probes.append(
            _probe(
                "macOS screen saver disabled",
                f"""
import subprocess, sys
try:
    result = subprocess.run({saver_argv!r}, capture_output=True, text=True, timeout=10)
except subprocess.TimeoutExpired:
    sys.exit(EXIT['probe_request_timed_out'])
except OSError:
    sys.exit(EXIT['probe_launch_failed'])
ok = result.returncode == 0 and result.stdout.strip() == '0'
sys.exit(0 if ok else EXIT['probe_check_unmet'])
""",
            )
        )
        probes.append(
            _probe(
                "macOS login keychain readable",
                """
import pathlib, subprocess, sys
try:
    result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w', str(pathlib.Path.home() / 'Library/Keychains/login.keychain-db')], capture_output=True, timeout=30)
except subprocess.TimeoutExpired:
    sys.exit(EXIT['probe_request_timed_out'])
except OSError:
    sys.exit(EXIT['probe_launch_failed'])
ok = result.returncode == 0 and bool(result.stdout.strip())
sys.exit(0 if ok else EXIT['probe_check_unmet'])
""",
            )
        )
    if os_name == "linux":
        probes.append(
            _probe(
                "Linux desktop input available",
                """
import pathlib, shutil, sys
# Detect desktop provisioning after logout; the home archive does not own OS packages.
desktop = any(pathlib.Path('/usr/share/xsessions').glob('*.desktop')) or shutil.which('xfce4-session') is not None
sys.exit(0 if not desktop or shutil.which('xdotool') else EXIT['probe_check_unmet'])
""",
            )
        )
    return probes


def capture_probes_document(
    os_name: str, document: str | None
) -> tuple[str | None, HostActionResult | None]:
    """Select defaults or refuse a document missing a mandatory check."""
    from yoke_harness.ssh_mac_baseline_probes import parse_baseline_probes

    standard = standard_probes(os_name)
    if document is None:
        return json.dumps({"probes": standard}), None
    try:
        supplied = parse_baseline_probes(document)
    except ValueError:
        return None, HostActionResult(
            False,
            {"recovery": f"Correct the probe JSON; follow {CHECKLIST}."},
            "baseline_probes_invalid",
        )
    names = {probe.name for probe in supplied}
    missing = [probe["name"] for probe in standard if probe["name"] not in names]
    if missing:
        return None, HostActionResult(
            False,
            {
                "missing_probes": missing,
                "reason": "Missing standard probes: " + ", ".join(missing),
                "recovery": f"Include the named standard checks or omit --probes-file; follow {CHECKLIST}.",
            },
            "baseline_standard_probes_missing",
        )
    # Names cannot certify a check: always run/seal canonical standard programs.
    # Additional operator checks retain their argv and output expectations.
    extras = [
        dict(
            name=p.name,
            argv=list(p.argv),
            **(
                {"expect_output_contains": p.expect_output_contains}
                if p.expect_output_contains
                else {}
            ),
        )
        for p in supplied
        if p.name not in {p["name"] for p in standard}
    ]
    selected = json.dumps({"probes": [*standard, *extras]})
    try:
        parse_baseline_probes(selected)
    except ValueError:
        return None, HostActionResult(
            False,
            {
                "recovery": "Reduce additional probes so the complete standard set fits the probe limit."
            },
            "baseline_probes_invalid",
        )
    return selected, None
