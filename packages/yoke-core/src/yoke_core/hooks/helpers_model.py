"""Requested-model detection chain for hook owners.

Owns the parent-argv / env / placeholder-aware resolution of the model a
session was *asked* to run. What a provider actually served is a
different fact read from a different place — the harness's own transcript
or conversation store — and lands in separate columns; nothing here ever
answers that question.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from yoke_core.hooks.helpers_identity import detect_executor, is_codex


def _read_parent_argv() -> list[str]:
    """Return the parent process's argv as a whitespace-split token list.

    ``ps -p PID -o args=`` joins argv with spaces, which is lossy for args
    that contain whitespace but is fine for scanning flag/value pairs whose
    values are model IDs (no spaces). Returns an empty list on any failure
    so callers can skip silently.
    """
    try:
        ppid = os.getppid()
    except OSError:
        return []
    if ppid <= 1:
        return []
    try:
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    return result.stdout.strip().split()


# Model-ID values that some harness surfaces pass as placeholders
# ("use whatever the user has configured") rather than as authoritative
# model IDs. VS Code extension <= 2.1.77 launched Claude Code with
# ``--model default`` — treating that literal string as a real model ID
# mis-reports every VS Code session's model in telemetry. Noninteractive
# Claude SDK invocations can report bracketed placeholders such as
# ``<synthetic>`` before a concrete transcript model exists. (The 2.1.112+
# extension drops the ``--model`` flag entirely, which has the same
# net effect on detection: no usable signal from argv.) Normalize any
# such placeholder to the empty string so callers fall through to the
# next precedence source.
_PLACEHOLDER_MODEL_VALUES = frozenset({"", "default", "auto", "unknown"})


def _is_placeholder_model(value: object) -> bool:
    """Return True if *value* is a known non-authoritative placeholder."""
    if not isinstance(value, str):
        return True
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_MODEL_VALUES:
        return True
    return normalized.startswith("<") and normalized.endswith(">")


def _extract_model_from_argv(argv: list[str]) -> str:
    """Scan argv for ``--model VALUE`` or ``--model=VALUE``.

    Preserves any ``[variant]`` suffix on the model ID (e.g. ``[1m]`` for
    1M-context variants) — the suffix is useful provenance and downstream
    telemetry can normalize it if needed.

    Returns ``""`` when the flag's value is a placeholder such as
    ``default`` (used by VS Code extension <= 2.1.77 to mean "use the
    user-selected default") so callers can continue their precedence
    chain instead of recording a bogus model ID. Also returns ``""``
    when the flag is absent entirely (VS Code 2.1.112+ omits it).
    """
    for i, arg in enumerate(argv):
        if arg == "--model" and i + 1 < len(argv):
            val = argv[i + 1]
            return "" if _is_placeholder_model(val) else val
        if arg.startswith("--model="):
            val = arg[len("--model="):]
            return "" if _is_placeholder_model(val) else val
    return ""


def detect_requested_model(
    executor: Optional[str] = None,
) -> str:
    """Detect the model this session was *asked* to run.

    Every source here is request-side. A Yoke launch stamps ``YOKE_MODEL``;
    the harness CLI carries ``--model``; the surrounding environment names a
    default. None of them reports what a provider served — that answer is
    read from the harness's own artifact by
    :mod:`yoke_harness.model_attestation` and stored in separate columns.

    Precedence:

      1. ``YOKE_MODEL`` — explicit Yoke-side override, set by a launch.
      2. ``CODEX_MODEL`` on Codex; ``CLAUDE_MODEL`` on Claude Code (set by
         the CLI when invoked with ``--model``). Placeholders such as
         ``default`` are skipped.
      3. Parent process ``--model`` argv — authoritative under Desktop.
         VS Code gives no usable signal: <= 2.1.77 launches with the
         ``--model default`` placeholder, 2.1.112+ omits the flag.
      4. ``DEFAULT_LLM_MODEL`` — Desktop-exported default. Observed to lag
         the active model, but it is still a stated ask.
      5. ``"unknown"`` — no request signal is available.
    """
    if os.environ.get("YOKE_MODEL"):
        return os.environ["YOKE_MODEL"]
    if is_codex(executor or detect_executor()):
        codex_env = os.environ.get("CODEX_MODEL", "")
        if codex_env:
            return codex_env
    claude_env = os.environ.get("CLAUDE_MODEL", "")
    if claude_env and not _is_placeholder_model(claude_env):
        return claude_env
    argv_model = _extract_model_from_argv(_read_parent_argv())
    if argv_model:
        return argv_model
    default_env = os.environ.get("DEFAULT_LLM_MODEL", "")
    if default_env and not _is_placeholder_model(default_env):
        return default_env
    return "unknown"
