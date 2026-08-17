"""Probe the resolved ``python3`` interpreter for required Yoke deps.

Yoke skill recipes use the literal ``python3`` form (the docs root for
the ongoing migration to the ``yoke`` console script). On macOS, bare
``python3`` resolves to ``/usr/bin/python3`` — the Apple-shipped Python
3.9 — which is missing ``pydantic`` and other deps Yoke needs. The
result is an opaque ``ModuleNotFoundError`` on the first Yoke call in
a fresh shell whose PATH order favors Apple Python.

This module owns a fast pre-call probe: resolve the ``python3`` the
operator's shell will invoke, attempt to import a sentinel module
(``pydantic``), and return a typed result. Callers (``session_init``
stderr emit; ``main_agent_packet`` orientation block) gate their
advisory text on a confirmed missing-dep signal — never on uncertain
state. Fail open on timeout, missing interpreter, or non-pydantic
errors so the probe never blocks a working session.

Honors ``$YOKE_PYTHON`` override: when set, the probe checks that
interpreter instead of bare ``python3``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


SENTINEL_MODULE = "pydantic"

HOMEBREW_PYTHON_ARM = "/opt/homebrew/bin/python3"
HOMEBREW_PYTHON_INTEL = "/usr/local/bin/python3"

# The probe is capped at <100ms in the happy path. The upper-bound
# timeout below is generous so a cold-cache import on a busy system
# still completes; the no-op happy path lands well under the cap.
SUBPROCESS_TIMEOUT_S = 1.5

OVERRIDE_ENV_VAR = "YOKE_PYTHON"


@dataclass(frozen=True)
class ProbeResult:
    """Typed result of the interpreter probe.

    Attributes:
        ok: True when the resolved interpreter imports the sentinel,
            OR when the probe failed for any reason other than a
            confirmed missing dep (fail-open contract).
        resolved_python: Path to the interpreter that was probed. May
            be ``None`` when no ``python3`` could be resolved.
        missing_module: Name of the sentinel module that failed to
            import; populated only when ``ok`` is False AND the failure
            is a confirmed ``ModuleNotFoundError``. ``None`` for
            fail-open cases (timeout, exec failure, unexpected error).
        override_used: True when ``$YOKE_PYTHON`` was honored as the
            probe target. False when bare ``python3`` resolution was
            used.
    """

    ok: bool
    resolved_python: Optional[str]
    missing_module: Optional[str]
    override_used: bool


def _resolve_python_target() -> Tuple[Optional[str], bool]:
    """Return ``(interpreter_path, override_used)``."""
    override = os.environ.get(OVERRIDE_ENV_VAR, "").strip()
    if override:
        return override, True
    return shutil.which("python3"), False


def probe() -> ProbeResult:
    """Run the interpreter probe.

    Fail-open: any uncertain state (no interpreter resolved, subprocess
    timeout, unexpected exec failure, non-sentinel stderr) returns
    ``ok=True`` so the caller does not surface a noisy advisory on
    edge cases. Only a confirmed ``ModuleNotFoundError`` naming the
    sentinel produces ``ok=False``.
    """
    target, override_used = _resolve_python_target()
    if not target:
        return ProbeResult(
            ok=True, resolved_python=None,
            missing_module=None, override_used=override_used,
        )
    try:
        proc = subprocess.run(
            [target, "-c", f"import {SENTINEL_MODULE}"],
            capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ProbeResult(
            ok=True, resolved_python=target,
            missing_module=None, override_used=override_used,
        )
    if proc.returncode == 0:
        return ProbeResult(
            ok=True, resolved_python=target,
            missing_module=None, override_used=override_used,
        )
    stderr = proc.stderr or ""
    if "ModuleNotFoundError" in stderr and SENTINEL_MODULE in stderr:
        return ProbeResult(
            ok=False, resolved_python=target,
            missing_module=SENTINEL_MODULE, override_used=override_used,
        )
    return ProbeResult(
        ok=True, resolved_python=target,
        missing_module=None, override_used=override_used,
    )


def _launcher_python() -> Optional[str]:
    """Return the live ``yoke`` launcher's pinned Python, when declared."""
    launcher = shutil.which("yoke")
    if not launcher:
        return None
    try:
        with Path(launcher).open(encoding="utf-8") as stream:
            first_line = stream.readline().strip()
    except (OSError, UnicodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    candidate = first_line[2:].strip()
    if not os.path.isabs(candidate) or "python" not in Path(candidate).name:
        return None
    return candidate


def _imports_sentinel(target: str) -> bool:
    """Return whether an existing interpreter imports the sentinel now."""
    if not os.path.isfile(target) or not os.access(target, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [target, "-c", f"import {SENTINEL_MODULE}"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _recommended_python(*, exclude: Optional[str]) -> Optional[str]:
    """Return the first live, dependency-equipped interpreter candidate."""
    candidates = (
        _launcher_python(),
        sys.executable,
        HOMEBREW_PYTHON_ARM,
        HOMEBREW_PYTHON_INTEL,
    )
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate == exclude or candidate in seen:
            continue
        seen.add(candidate)
        if _imports_sentinel(candidate):
            return candidate
    return None


def render_advisory(result: ProbeResult) -> str:
    """Render the human-readable advisory for a confirmed probe failure.

    Returns ``""`` when ``result.ok`` is True so callers can emit the
    return value unconditionally — the empty advisory is the no-op
    shape.
    """
    if result.ok or not result.missing_module:
        return ""
    resolved = result.resolved_python or "<unresolved>"
    lines = [
        (
            f"Yoke interpreter check: resolved python3 ({resolved}) is "
            f"missing `{result.missing_module}`."
        ),
    ]
    recommendation = _recommended_python(exclude=result.resolved_python)
    if recommendation:
        lines.extend([
            f"Live interpreter: {recommendation}",
            (
                f"Fix: export {OVERRIDE_ENV_VAR}={recommendation}  "
                f"(or adjust PATH so this interpreter resolves first)."
            ),
        ])
    else:
        lines.extend([
            "No live pydantic-equipped Python interpreter was found.",
            (
                "Fix: repair the Yoke launcher or install pydantic, then set "
                f"{OVERRIDE_ENV_VAR} only to an interpreter that passes "
                f"`python3 -c 'import {SENTINEL_MODULE}'`."
            ),
        ])
    if result.override_used:
        lines.append(
            f"Note: {OVERRIDE_ENV_VAR} is already set but its target is "
            f"also missing {result.missing_module}."
        )
    return "\n".join(lines)
