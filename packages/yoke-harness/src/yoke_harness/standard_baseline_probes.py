"""Mandatory capture probes, sealed through the existing baseline document."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from yoke_harness import baseline_harness_requests
from yoke_harness.ssh_mac_host_session_state import (
    SCREEN_SAVER_DISABLE_COMMAND,
    SCREEN_SAVER_READ_COMMAND,
)
from yoke_harness.test_machine_types import HostActionResult

CHECKLIST = "docs/packs/machine-qa/host-provisioning.md"
RECOVERIES = {
    "Claude real request": "Sign in Claude with claude auth login in the test user's session.",
    "Codex real request": "Sign in Codex with codex login in the test user's session.",
    "Cursor real request": "Sign in Cursor with agent login in the test user's session.",
    "Claude bypass accepted": "Have the operator accept Claude's one-time bypass prompt in the test user's session.",
    "macOS login keychain readable": "Use GUI Terminal to unlock/re-key the login keychain after a password change, sign in Claude again, and re-save.",
    "macOS screen saver disabled": f"As the GUI test user run {SCREEN_SAVER_DISABLE_COMMAND} before capture; save a new golden and prove the reset roundtrip.",
    "Linux desktop input available": "Provision xdotool as a baseline package before capture, not as a QA package; capture a new golden and prove the fresh-host reset roundtrip.",
}


def standard_probe_recovery(name: str) -> str | None:
    step = RECOVERIES.get(name)
    return f"{step} Follow {CHECKLIST}, then retry capture/reset." if step else None


def _probe(name: str, program: str) -> dict:
    return {"name": name, "argv": ["/usr/bin/python3", "-c", program]}


def standard_probes(os_name: str) -> list[dict]:
    """Run harnesses without tools; only bounded success leaves the remote process."""
    if os_name not in {"macos", "linux", "windows"}:
        raise ValueError("baseline_probe_os_unsupported")
    source = Path(baseline_harness_requests.__file__).read_text(encoding="utf-8")
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
import os, shutil, subprocess, sys
from pathlib import Path
search = os.pathsep.join([str(Path.home() / '.local/bin'), os.environ.get('PATH', '')])
executable = next((p for x in {executables!r} if (p := shutil.which(x, path=search))), None)
if not executable: sys.exit(1)
request = harness_request([executable])
try:
    result = subprocess.run(request.argv, cwd=REQUEST_WORKSPACE, capture_output=True, text=True, timeout=110)
    ok = result.returncode == 0 and request.answered(result.stdout)
except (OSError, subprocess.TimeoutExpired):
    ok = False
sys.exit(0 if ok else 1)
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
sys.exit(0 if ok else 1)
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
    ok = result.returncode == 0 and result.stdout.strip() == '0'
except (OSError, subprocess.TimeoutExpired):
    ok = False
sys.exit(0 if ok else 1)
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
    ok = result.returncode == 0 and bool(result.stdout.strip())
except (OSError, subprocess.TimeoutExpired):
    ok = False
sys.exit(0 if ok else 1)
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
sys.exit(0 if not desktop or shutil.which('xdotool') else 1)
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
