"""Start or reuse the registered Linux user's real XFCE desktop over SSH."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_harness import linux_desktop_state
from yoke_harness.linux_command_custody import run_command


DESKTOP_PROGRAM = """
password = sys.stdin.read().removesuffix('\\n')
if sys.argv[3] == '1':
 sessions = desktop_sessions()
 if len(sessions) != 1 or human_desktop_exists(Path.home(), {**sessions[0], 'rdp_port': int(sys.argv[1])}):
  raise RuntimeError('linux_desktop_restart_in_use: close the RDP client and end other fixture logins before retrying the screenshot')
 if not password:
  raise RuntimeError('desktop_password_missing: store desktop_password before restarting the blank desktop')
 stop_desktop()
receipt = ensure_desktop(password, int(sys.argv[1]), rdp_access=sys.argv[2] == '1')
if sys.argv[3] == '1':
 receipt['desktop_session'] = 'restarted'
print(json.dumps(receipt))
"""


def ensure_desktop(control, *, restart=False):
    source = Path(linux_desktop_state.__file__).read_text()
    program = (
        source
        + "\nimport sys\ntry:\n"
        + "\n".join(" " + line for line in DESKTOP_PROGRAM.splitlines())
        + "\nexcept (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:\n print(str(exc), file=sys.stderr); sys.exit(69)"
    )
    probe = control._run(
        shlex.join(
            [
                "/usr/bin/python3",
                "-c",
                program,
                str(getattr(control, "desktop_port", linux_desktop_state.RDP_PORT)),
                "1" if getattr(control, "rdp_access", False) else "0",
                "1" if restart else "0",
            ]
        ),
        input_text=(getattr(control, "desktop_password", None) or "") + "\n",
        timeout=60,
    )
    if probe.returncode:
        detail = probe.stdout + probe.stderr
        for secret in getattr(control, "secret_values", ()):
            detail = detail.replace(secret, "[REDACTED]")
        raise RuntimeError(
            compose_refusal(
                "linux_desktop_session_required",
                evaluated=detail,
                recovery=linux_desktop_state.RECOVERY,
            )
        )
    try:
        receipt = json.loads(probe.stdout)
        if (
            receipt["desktop_session"] not in {"started", "reused", "restarted"}
            or not receipt["environment"]["DISPLAY"]
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise RuntimeError(
            "linux_desktop_receipt_invalid: " + linux_desktop_state.RECOVERY
        ) from None
    control.desktop_session = receipt["desktop_session"]
    return receipt


def desktop_command(control, argv: list[str], *, timeout: int = 60):
    """Run on the same display screenshots capture, carrying startup evidence."""
    receipt = ensure_desktop(control)
    result = run_command(control, argv, receipt["environment"], timeout=timeout)
    result.desktop_session = receipt["desktop_session"]
    return result
