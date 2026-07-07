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
stderr emit; ``bootstrap_packets`` orientation block) gate their
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
from dataclasses import dataclass
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


def _canonical_homebrew_python() -> str:
    """Return the canonical Homebrew ``python3`` path for this host.

    Apple Silicon installs land under ``/opt/homebrew``; Intel macs land
    under ``/usr/local``. Falls back to the Apple-Silicon path when
    neither exists so the advisory still names a copy-pasteable command.
    """
    if os.path.exists(HOMEBREW_PYTHON_ARM):
        return HOMEBREW_PYTHON_ARM
    if os.path.exists(HOMEBREW_PYTHON_INTEL):
        return HOMEBREW_PYTHON_INTEL
    return HOMEBREW_PYTHON_ARM


def render_advisory(result: ProbeResult) -> str:
    """Render the human-readable advisory for a confirmed probe failure.

    Returns ``""`` when ``result.ok`` is True so callers can emit the
    return value unconditionally — the empty advisory is the no-op
    shape.
    """
    if result.ok or not result.missing_module:
        return ""
    homebrew = _canonical_homebrew_python()
    resolved = result.resolved_python or "<unresolved>"
    lines = [
        (
            f"Yoke interpreter check: resolved python3 ({resolved}) is "
            f"missing `{result.missing_module}`."
        ),
        f"Canonical interpreter: {homebrew}",
        (
            f"Fix: export {OVERRIDE_ENV_VAR}={homebrew}  "
            f"(or adjust PATH so a pydantic-equipped python3 resolves "
            f"first)."
        ),
    ]
    if result.override_used:
        lines.append(
            f"Note: {OVERRIDE_ENV_VAR} is already set but its target is "
            f"also missing {result.missing_module}."
        )
    return "\n".join(lines)
