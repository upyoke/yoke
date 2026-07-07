"""Codex hook payload, identity, runtime cache, and fire-once markers.

Owns the input-side surface of the Codex hook chain: stdin parsing,
top-level field extraction, session/root/yoke-db resolution, the
``/tmp`` runtime cache that lets prompt-submit reuse SessionStart
context, and the fire-once marker primitives.

Imported by :mod:`runtime.harness.hook_runner` (the shared hook
front door for both Claude and Codex) for the codex-hook input
parsing surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_core.domain.project_scratch_dir import harness_runtime_cache_path, hook_marker_path

GIT_TIMEOUT_S = 5


# ---------------------------------------------------------------------------
# stdin + payload helpers
# ---------------------------------------------------------------------------


def read_stdin() -> str:
    """Best-effort stdin read. Returns empty string on any failure."""
    try:
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def _parse_payload(payload: str) -> Dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def payload_field(payload: str, field: str) -> str:
    """Extract a top-level field from hook JSON as a string.

    Booleans stringify to ``"true"``/``"false"`` so downstream callers can
    check ``stop_hook_active`` without re-parsing.  ``None`` becomes ``""``.
    """
    data = _parse_payload(payload)
    value = data.get(field, "")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Identity + root resolution
# ---------------------------------------------------------------------------


def resolve_session_id(payload: str) -> str:
    """Resolve Codex session identity.

    Resolution order:
      1. ``CODEX_THREAD_ID``
      2. ``YOKE_SESSION_ID``
      3. payload ``session_id``

    Returns empty string when no source has a value.  Callers decide
    whether to short-circuit, emit a degraded-mode warning, etc.
    """
    thread = os.environ.get("CODEX_THREAD_ID", "")
    if thread:
        return thread
    yoke_sid = os.environ.get("YOKE_SESSION_ID", "")
    if yoke_sid:
        return yoke_sid
    return payload_field(payload, "session_id")


def resolve_root(payload: str = "") -> str:
    """Resolve the workspace the Codex harness opened at.

    Resolution order (harness-workspace semantics, payload-first):
      1. Hook payload ``cwd`` — the launch-time workspace Codex adopts for
         this session. Stable across mid-session shell cwd drift, which
         makes it the right analogue of Claude Code's
         ``CLAUDE_PROJECT_DIR`` for the purpose of gating telemetry on
         "what project is the harness opened at."
      2. ``YOKE_ROOT`` env var — explicit pin, usually set by an entry
         wrapper when payload cwd is unavailable.
      3. ``git rev-parse --show-toplevel`` — live-cwd fallback. Moves
         with the shell, so only correct when the session has not drifted
         out of the Yoke tree.

    Returns empty string when no source resolves; callers degrade
    gracefully rather than raising.
    """
    cwd = payload_field(payload, "cwd") if payload else ""
    if cwd:
        return cwd
    root = os.environ.get("YOKE_ROOT", "")
    if root:
        return root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def resolve_yoke_db(root: str) -> str:
    """Resolve the legacy DB token used by hook-owned Python modules."""
    from runtime.harness.codex.codex_db_resolution import (
        resolve_yoke_db as _resolve_yoke_db,
    )

    return _resolve_yoke_db(root)


def is_yoke_target(root: str, yoke_db: str) -> bool:
    """Return True when the hook should run for this workspace."""
    try:
        from runtime.harness.hook_runner.target import (
            is_yoke_target as _shared_is_yoke_target,
        )

        return _shared_is_yoke_target(root, yoke_db)
    except Exception:
        return bool(root and yoke_db and Path(yoke_db).is_file())


# ---------------------------------------------------------------------------
# Runtime cache (per-session payload persistence for prompt-submit)
# ---------------------------------------------------------------------------


def prompt_marker_path(session_id: str) -> str:
    """Return the fire-once prompt marker path for *session_id*."""
    return str(hook_marker_path(f"codex-prompt-{session_id}"))


def session_marker_path(session_id: str) -> str:
    """Return the fire-once session marker path for *session_id*."""
    return str(hook_marker_path(f"codex-session-{session_id}"))


def runtime_cache_path(session_id: str) -> str:
    """Return the per-session runtime-cache JSON path."""
    return str(harness_runtime_cache_path(f"codex-runtime-{session_id}.json"))


def write_runtime_cache(session_id: str, payload: str) -> None:
    """Persist the raw SessionStart payload so subsequent prompts can reuse
    fields like ``transcript_path`` and ``source`` when the prompt payload
    omits them."""
    if not session_id or not payload:
        return
    try:
        with open(runtime_cache_path(session_id), "w", encoding="utf-8") as handle:
            handle.write(payload)
            if not payload.endswith("\n"):
                handle.write("\n")
    except OSError:
        pass


def read_runtime_cache_field(session_id: str, field: str) -> str:
    """Read a top-level field from the runtime cache, or empty string."""
    try:
        with open(runtime_cache_path(session_id), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get(field, "")
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Tool-event normalization shim
# ---------------------------------------------------------------------------
#
# Local typed shape that mirrors the cross-harness ``ToolEventRecord``
# contract documented in worktree H's task body. When task 003 (worktree H) lands
# in ``yoke_core.domain.observe_normalization``, this shim is replaced
# wholesale by ``from yoke_core.domain.observe_normalization import
# ToolEventRecord`` so call sites do not have to move. Field names are
# identical to the documented contract.

# ``tool_kind`` is the tool-class-neutral discriminator. ``apply_patch``
# rides the same cross-harness shape Claude's ``Write``/``Edit`` already
# feeds; the discriminator is what H/R/P sibling worktrees branch on to apply
# patch-scoped guardrails (path-claim check, observe coverage, etc.).


@dataclass
class ToolEventRecord:
    """Cross-harness normalized tool-event shape (local shim).

    Mirrors the documented contract from worktree H. ``tool_kind`` collapses
    Claude/Codex tool-name variance into a small enumeration; downstream
    code branches on ``tool_kind``, never on the harness-native
    ``tool_name`` string.

    Replacement target: worktree H's ``yoke_core.domain.observe_normalization
    .ToolEventRecord`` (same field names).
    """

    tool_kind: str = ""
    tool_name: str = ""
    hook_event: str = ""
    session_id: str = ""
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    file_path: str = ""
    command: str = ""
    changed_paths: List[str] = field(default_factory=list)
    cwd: str = ""
    project_dir: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)


_PATCH_TOOL_KINDS = {
    "apply_patch": "apply_patch",
    "Write": "write",
    "Edit": "edit",
}


def normalize_tool_event(payload: str, hook_event: str) -> ToolEventRecord:
    """Build a :class:`ToolEventRecord` from a raw Codex hook payload.

    Recognizes the patch/edit/write tool kinds documented for this worktree
    plus ``Bash`` (kept lightweight — full Bash normalization stays in the
    existing observe pipeline). For ``apply_patch``, ``changed_paths`` is
    populated from the patch body via
    :func:`yoke_core.domain.observe_apply_patch_parser.parse_patch_body`.
    """
    data = _parse_payload(payload)
    tool_name = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    rec = ToolEventRecord(
        tool_kind=_PATCH_TOOL_KINDS.get(tool_name, tool_name.lower() or ""),
        tool_name=tool_name,
        hook_event=hook_event,
        session_id=str(data.get("session_id") or ""),
        tool_use_id=(str(data["tool_use_id"]) if data.get("tool_use_id") else None),
        turn_id=(str(data["turn_id"]) if data.get("turn_id") else None),
        cwd=str(data.get("cwd") or ""),
        project_dir=str(data.get("project_dir") or data.get("cwd") or ""),
        raw_payload=data,
    )

    if tool_name == "apply_patch":
        body = tool_input.get("command") or tool_input.get("input") or ""
        if isinstance(body, str):
            rec.command = body
            from yoke_core.domain.observe_apply_patch_parser import (
                parse_patch_body,
            )

            summary = parse_patch_body(body)
            rec.changed_paths = list(summary.changed_paths)
    elif tool_name in ("Write", "Edit"):
        fp = tool_input.get("file_path") or ""
        if isinstance(fp, str):
            rec.file_path = fp
            if fp:
                rec.changed_paths = [fp]
    elif tool_name == "Bash":
        cmd = tool_input.get("command") or ""
        if isinstance(cmd, str):
            rec.command = cmd

    return rec


# ---------------------------------------------------------------------------
# Fire-once markers
# ---------------------------------------------------------------------------


def check_and_arm_marker(marker_path: str) -> bool:
    """Return ``True`` if this is the first call (and arm the marker).

    A pre-existing marker means "already fired" and returns ``False``.
    The marker is created atomically so concurrent hook processes cannot
    both fire for the same session.  Any filesystem error falls through
    silently -- hook paths must never crash on /tmp weirdness.
    """
    try:
        fd = os.open(marker_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return True
    try:
        os.close(fd)
    except OSError:
        pass
    return True
