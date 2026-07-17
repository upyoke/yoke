"""PreToolUse Write lint: refuse direct Yoke imports in ``/tmp`` Python.

Agents that reach for Python authoring as a fallback for "dispatch a
function-call" land
the script at ``/tmp/<name>.py`` and then fail at run time with
``ModuleNotFoundError: No module named 'runtime'`` because Python's
``sys.path[0]`` for ``python3 /tmp/foo.py`` is the script's directory,
not the caller's cwd.

The structural fix is to refuse the ``Write`` call before the bad file
lands. The deny reason teaches the canonical alternatives: place the
script under ``runtime/api/tools/<name>.py`` (in-tree, supports imports
natively), or use the registered ``yoke <subcommand>`` CLI adapter for
the underlying operation (no Python authoring needed).

Allowed shapes the lint stays out of:

* Markdown / JSON / text files in ``/tmp`` (no runtime imports).
* Python files under the repo tree (``runtime/...``, ``packages/...``,
  ``projects/...``).
* Python under a real Yoke checkout/worktree provisioned in ``/tmp`` —
  i.e. inside ``<root>/runtime/`` or ``<root>/packages/`` where ``<root>``
  carries both a ``.git`` entry and ``pyproject.toml``. Conduct/workflow
  fan-out worktrees live under ``/tmp`` by design and resolve Yoke package
  imports natively from the worktree root; only standalone ``/tmp/foo.py``
  scratch scripts hit the ``sys.path[0]`` hazard this lint guards.
* Editable-install Python anywhere (``pip install -e .`` is declared in
  ``pyproject.toml``; once installed, scripts can live anywhere).

Bypass: ``# lint:no-tmp-runtime-import-check`` on the file content is
audit-only (recorded as ``outcome=suppression_attempted``) — the rule
still denies. The canonical workaround is to move the script into the
repo tree.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


_BYPASS_TOKEN = "# lint:no-tmp-runtime-import-check"

# Free-path roots under which a Python file with ``runtime.*`` imports
# is structurally unable to find the package via ``sys.path[0]``.
_TMP_PREFIXES = (
    "/tmp/",
    "/var/folders/",
    "/private/tmp/",
    "/private/var/folders/",
)

# Lines like ``import yoke_core`` / ``import runtime.api.x`` /
# ``from yoke_core.foo import bar`` (handles indented + multiline). Block
# comments and docstring mentions are not import statements so the
# anchor on ``^\s*(from|import)`` keeps the match precise.
_FORBIDDEN_IMPORT_PREFIX_RE = (
    r"(?:"
    r"yoke_core(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_cli(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_harness(?:\.[A-Za-z_][\w]*)*|"
    r"runtime(?:\.(?:api|harness|agents)(?:\.[A-Za-z_][\w]*)*)?"
    r")"
)
_RUNTIME_IMPORT_RE = re.compile(
    rf"^\s*(?:"
    rf"from\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\s+import\b|"
    rf"import\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\b"
    rf")",
    re.MULTILINE,
)

_DENY_REASON = (
    "BLOCKED: Python script under /tmp imports Yoke implementation modules — will fail with "
    "ModuleNotFoundError at run time.\n\n"
    "Python's `sys.path[0]` for `python3 /tmp/foo.py` is the script's "
    "directory (/tmp), not your cwd, so direct imports of `yoke_core.*` "
    "or transitional `runtime.*` modules cannot find the Yoke package "
    "unless the environment was explicitly bootstrapped.\n\n"
    "Clean alternatives (preferred order):\n"
    "  1. Registered CLI adapter — most one-off DB writes need no Python at all:\n"
    "       printf '%s' \"$content\" | yoke items structured-field replace "
    "YOK-N --field <field> --stdin\n"
    "  2. In-tree Python — place the script under runtime/api/tools/<name>.py "
    "where the package layout supports imports natively.\n"
    "  3. Editable install — `pip install -e /Users/<...>/yoke` once; "
    "scripts then run from any cwd.\n\n"
    "For ephemeral scratch files (capture, payload, sentinel) Yoke code "
    "needs alongside the script, prefer the helper-resolved root from "
    "`yoke_core.domain.project_scratch_dir` (storage_path / "
    "watcher_capture_path / ephemeral_payload / scratch_subdir) rather "
    "than constructing a literal /tmp/yoke-* path — the helper keeps "
    "writes under one root the orphan scanner already knows.\n\n"
    "Suppression: `# lint:no-tmp-runtime-import-check` in the file content "
    "is audit-only (the rule still denies)."
)


def _extract_tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _extract_write_fields(payload: dict) -> tuple[str, str]:
    """Return ``(file_path, content)`` for a Write tool call, or ``("", "")``."""
    tool_input = _extract_tool_input(payload)
    file_path = tool_input.get("file_path") or tool_input.get("filePath") or ""
    content = tool_input.get("content") or tool_input.get("body") or ""
    if not isinstance(file_path, str):
        file_path = ""
    if not isinstance(content, str):
        content = ""
    return file_path, content


def _is_tmp_python_path(file_path: str) -> bool:
    if not file_path or not file_path.endswith(".py"):
        return False
    return any(file_path.startswith(prefix) for prefix in _TMP_PREFIXES)


def _under_tmp_yoke_checkout(file_path: str) -> bool:
    """True when a /tmp ``file_path`` sits inside a real Yoke checkout's
    ``runtime/`` package or package source tree.

    A linked worktree (or full checkout) provisioned under /tmp — the
    standard shape for conduct/workflow fan-out — is a real package tree
    where Yoke package imports resolve under pytest / ``python3 -m`` run
    from the worktree root. The original ``sys.path[0]`` hazard only bites a
    *standalone* ``/tmp/foo.py`` with no checkout above it.

    Exempt ONLY when an ancestor directory carries BOTH a ``.git`` entry
    (a directory for a checkout, a file for a linked worktree) AND
    ``pyproject.toml`` (the checkout root), AND the target lives under that
    root's ``runtime/`` package or ``packages/`` source tree. A stray
    ``/tmp/foo.py`` — or a marked checkout root with the script outside those
    source roots — stays blocked.
    """
    parent = os.path.dirname(file_path)
    while parent and parent != os.path.dirname(parent):
        try:
            has_git = os.path.exists(os.path.join(parent, ".git"))
            has_pyproject = os.path.isfile(os.path.join(parent, "pyproject.toml"))
        except OSError:
            has_git = has_pyproject = False
        if has_git and has_pyproject:
            try:
                rel = os.path.relpath(file_path, parent)
            except ValueError:
                return False
            return (
                rel == "runtime"
                or rel.startswith("runtime" + os.sep)
                or rel == "packages"
                or rel.startswith("packages" + os.sep)
            )
        parent = os.path.dirname(parent)
    return False


def _content_imports_runtime(content: str) -> bool:
    return bool(_RUNTIME_IMPORT_RE.search(content))


def evaluate_fields(file_path: str, content: str) -> Optional[str]:
    """Return a denial reason when the Write would create a /tmp/*.py
    that imports ``runtime.*``."""
    if not _is_tmp_python_path(file_path):
        return None
    if _under_tmp_yoke_checkout(file_path):
        return None
    if not _content_imports_runtime(content):
        return None
    return append_field_note_footer(_DENY_REASON, rule_id="lint-python-runtime-import-in-tmp")


def evaluate_payload(payload: dict) -> Optional[str]:
    file_path, content = _extract_write_fields(payload)
    return evaluate_fields(file_path, content)


def _build_deny_response(reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def _emit_denial(payload: dict, reason: str, *, outcome: str = "denied") -> None:
    """Best-effort ``HarnessToolCallDenied`` audit event."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    _s = lambda v: v if isinstance(v, str) else ""  # noqa: E731
    file_path, _ = _extract_write_fields(payload)
    try:
        emit_denial_event(
            hook="lint-python-runtime-import-in-tmp", tool="Write",
            check_id="python_runtime_import_in_tmp", reason=reason,
            session_id=_s(payload.get("session_id")),
            tool_use_id=_s(payload.get("tool_use_id")),
            turn_id=_s(payload.get("turn_id") or payload.get("message_id")),
            command_snippet=file_path, outcome=outcome)
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Wraps :func:`evaluate_payload`; the bypass token is
    audit-only — the rule still denies."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    file_path, content = _extract_write_fields(payload)
    reason = evaluate_fields(file_path, content)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    outcome = ("suppression_attempted" if _BYPASS_TOKEN in content else "denied")
    envelope = json.dumps(_build_deny_response(reason))
    _emit_denial(payload, reason, outcome=outcome)
    return HookDecision(outcome=Outcome.DENY, message=envelope,
        audit_fields={"reason": reason, "audit_outcome": outcome},
        block=True, next=Next.STOP)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload, tool_name="Write",
        command_body=None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None)


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


__all__ = ["evaluate", "evaluate_fields", "evaluate_payload", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
