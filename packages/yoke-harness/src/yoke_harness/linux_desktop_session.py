"""Start or reuse the registered Linux user's real XFCE desktop over SSH."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from yoke_harness import linux_desktop_state


def ensure_desktop(control):
    source = Path(linux_desktop_state.__file__).read_text()
    program = (
        source
        + "\nimport sys\ntry:\n print(json.dumps(ensure_desktop(sys.stdin.read().removesuffix('\\n'), int(sys.argv[1]))))\nexcept (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:\n print(str(exc), file=sys.stderr); sys.exit(69)"
    )
    probe = control._run(
        shlex.join(
            [
                "/usr/bin/python3",
                "-c",
                program,
                str(getattr(control, "desktop_port", linux_desktop_state.RDP_PORT)),
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
            "linux_desktop_session_required: "
            + detail
            + "; "
            + linux_desktop_state.RECOVERY
        )
    try:
        receipt = json.loads(probe.stdout)
        if (
            receipt["desktop_session"] not in {"started", "reused"}
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
    result = control._run(
        shlex.join(
            [
                "env",
                *[f"{key}={value}" for key, value in receipt["environment"].items()],
                *argv,
            ]
        ),
        timeout=timeout,
    )
    result.desktop_session = receipt["desktop_session"]
    return result
