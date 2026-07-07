"""Model-detection chain for hook owners.

Owns the parent-argv / transcript / placeholder-aware model resolution
that every hook owner reaches for when no SessionStart payload is
available. SessionStart itself takes ``model`` straight from the
payload — this module is the fallback path used by
``UserPromptSubmit`` re-registration and operator-driven CLI probes.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from runtime.harness.hook_helpers_identity import detect_executor, is_codex


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


def _read_model_from_transcript(transcript_path: Optional[str]) -> str:
    """Scan a Claude Code transcript JSONL for the most recent assistant
    message's ``model`` field.

    Transcript entries look like ``{"type": "assistant", "message":
    {"model": "claude-opus-4-7", ...}}``. We walk the tail of the file
    in reverse so the latest model wins when a user swaps models
    mid-session. Returns ``""`` on any error or if no non-placeholder
    model ID is present.

    This is only useful once at least one assistant turn has completed
    (empty on the very first UserPromptSubmit), so callers must treat
    transcript-based detection as a late-arriving signal and pair it
    with an opportunistic refresh of ``harness_sessions.model``.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = raw.splitlines()
    # Cap the scan so a long-running session doesn't blow up the hook.
    for line in reversed(lines[-500:]):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message")
        if isinstance(msg, dict):
            model = msg.get("model")
            if isinstance(model, str) and not _is_placeholder_model(model):
                return model
    return ""


def detect_model(
    executor: Optional[str] = None,
    transcript_path: Optional[str] = None,
) -> str:
    """Detect the model name with safe defaults.

    This is the *fallback* model-detection path used by hooks that don't
    have direct access to a SessionStart payload. The SessionStart hook
    itself pulls ``model`` straight out of its payload (authoritative on
    every Claude Code surface) and passes it to ``register_session``, so
    most sessions never reach this function with a real signal to resolve.
    This function remains useful for: (a) UserPromptSubmit's idempotent
    safety-net re-registration when SessionStart was missed entirely,
    (b) operators invoking ``hook_helpers detect-model`` directly.

    Precedence:

      1. ``YOKE_MODEL`` — explicit Yoke-side override.
      2. ``CLAUDE_MODEL`` — set by the Claude Code CLI when invoked with
         ``--model`` (CLI path). Skipped when the value is a placeholder
         such as ``default``.
      3. Parent process ``--model`` argv — authoritative under Desktop
         (launches with ``--model <id>``). VS Code gives no usable signal
         here: <= 2.1.77 launches with the ``--model default`` placeholder,
         2.1.112+ omits the flag entirely.
      4. Claude Code transcript at *transcript_path* — walks the transcript
         tail for the latest assistant message's ``model`` field. Empty on
         the first turn, authoritative thereafter.
      5. ``DEFAULT_LLM_MODEL`` — Desktop-exported default. Observed to lag
         behind the active model (stale), but still better than a literal.
         Skipped when the value is a placeholder such as ``default``.
      6. ``"unknown"`` — last resort when no signal is available. Using a
         placeholder here (rather than a real model ID) lets the
         sessions_lifecycle refresh logic upgrade the stored value on the
         next prompt once the transcript reveals the true model.
    """
    if os.environ.get("YOKE_MODEL"):
        return os.environ["YOKE_MODEL"]
    if is_codex(executor or detect_executor()):
        env_model = os.environ.get("CODEX_MODEL", "")
        if env_model:
            return env_model
        from runtime.harness.codex.codex_model import resolve

        # Honest chain (env -> transcript -> cache); never fabricate a
        # concrete model — "unknown" stays upgradeable by the registry.
        return resolve() or "unknown"
    claude_env = os.environ.get("CLAUDE_MODEL", "")
    if claude_env and not _is_placeholder_model(claude_env):
        return claude_env
    argv_model = _extract_model_from_argv(_read_parent_argv())
    if argv_model:
        return argv_model
    transcript_model = _read_model_from_transcript(transcript_path)
    if transcript_model:
        return transcript_model
    default_env = os.environ.get("DEFAULT_LLM_MODEL", "")
    if default_env and not _is_placeholder_model(default_env):
        return default_env
    return "unknown"
