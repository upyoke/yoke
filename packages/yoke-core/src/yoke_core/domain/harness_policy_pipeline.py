"""Shared PreToolUse policy pipeline — harness-neutral dispatcher.

Adapters (Claude / Codex) translate their native PreToolUse payload to
:class:`ToolEventRecord`, then call :func:`dispatch`. The pipeline:

1. Maps ``tool_kind`` -> ordered policy module list via
   :mod:`harness_hook_ordering`.
2. For each module in the list, materialises the ``decide_for_record``
   entry point (when present) and invokes it with the record.
3. Returns a :class:`PipelineResult` summarising allow/deny decisions
   so the harness adapter can render the harness-native verdict.

Policy modules opt in by defining a top-level
``decide_for_record(record: ToolEventRecord) -> Optional[PolicyDecision]``.
Modules that don't define the function are treated as no-ops (allow).
This keeps the contract one-directional: the pipeline reads existing
``lint_*`` / ``observe_pre`` / ``path_claim_*`` modules without forcing
them to be rewritten — adapter authors (lanes K, R) wire the existing
JSON-stdin protocol when ``decide_for_record`` is absent.

Public surface:

- :class:`PolicyDecision` — outcome from a single policy module.
- :class:`PipelineResult` — aggregate verdict across the chain.
- :func:`dispatch` — run a record through its ordered chain.
- :func:`build_tool_event_record` — adapter helper to construct a
  record from raw PreToolUse hook fields.
- :func:`tool_kind_for` — translate a native tool name to the
  harness-neutral ``tool_kind``.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain.observe_apply_patch_parser import parse_patch
from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)


# Native tool name -> harness-neutral ``tool_kind`` mapping. Both Claude
# (``Bash``/``Edit``/``Write``) and Codex (``shell``/``apply_patch``)
# tool names are covered. Unknown tools (Read, Monitor, etc.) return
# ``None`` and the pipeline treats them as a no-op.
_TOOL_NAME_TO_KIND: Dict[str, str] = {
    "Bash": TOOL_KIND_BASH,
    "bash": TOOL_KIND_BASH,
    "shell": TOOL_KIND_BASH,
    "Write": TOOL_KIND_WRITE,
    "write": TOOL_KIND_WRITE,
    "Edit": TOOL_KIND_EDIT,
    "edit": TOOL_KIND_EDIT,
    "apply_patch": TOOL_KIND_APPLY_PATCH,
    "ApplyPatch": TOOL_KIND_APPLY_PATCH,
}


# Map ``tool_kind`` -> the matcher key used in
# :mod:`harness_hook_ordering.HOOK_ORDERING`. ``edit`` and ``write``
# both feed a write-shaped chain; ``apply_patch`` has its own matcher
# because Codex emits a multi-file diff.
_TOOL_KIND_TO_MATCHER: Dict[str, str] = {
    TOOL_KIND_BASH: "Bash",
    TOOL_KIND_EDIT: "Edit",
    TOOL_KIND_WRITE: "Write",
    TOOL_KIND_APPLY_PATCH: "apply_patch",
}


@dataclass
class PolicyDecision:
    """Outcome from a single policy module.

    ``allow`` is the only allow shape; everything else (``deny``,
    ``warn``, ``error``) carries a non-empty ``reason``. ``module``
    records the policy module id so callers can log which guard
    produced the decision.
    """

    outcome: str = "allow"  # allow | deny | warn | error
    reason: str = ""
    module: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Aggregate verdict across an ordered policy chain."""

    decisions: List[PolicyDecision] = field(default_factory=list)
    denied: bool = False
    deny_reason: str = ""
    deny_module: str = ""

    def first_deny(self) -> Optional[PolicyDecision]:
        for decision in self.decisions:
            if decision.outcome == "deny":
                return decision
        return None


def tool_kind_for(tool_name: str) -> Optional[str]:
    """Return the harness-neutral ``tool_kind`` for a native tool name.

    Returns ``None`` for tools the pipeline does not model (Read,
    Monitor, ScheduleWakeup, TaskOutput, etc.). The hook-ordering
    module has chains for those tools that are exclusively observation
    (``observe_pre`` / ``hint_monitor_relay``); they bypass dispatch.
    """
    if not tool_name:
        return None
    return _TOOL_NAME_TO_KIND.get(tool_name)


def build_tool_event_record(
    *,
    tool_name: str,
    tool_input: Optional[dict] = None,
    session_id: str = "",
    tool_use_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    cwd: str = "",
    project_dir: str = "",
) -> Optional[ToolEventRecord]:
    """Build a :class:`ToolEventRecord` from raw PreToolUse hook fields.

    Returns ``None`` when the tool is not modelled. Tolerant of
    malformed ``tool_input`` shapes — missing keys bottom out as empty
    strings or empty lists rather than raising.
    """
    kind = tool_kind_for(tool_name)
    if kind is None:
        return None

    inputs = tool_input or {}
    command = ""
    patch_body = ""
    changed: List[str] = []

    if kind == TOOL_KIND_BASH:
        command = str(inputs.get("command", "") or "")
    elif kind in (TOOL_KIND_WRITE, TOOL_KIND_EDIT):
        path = str(inputs.get("file_path", "") or "")
        if path:
            changed = [path]
    elif kind == TOOL_KIND_APPLY_PATCH:
        # Codex emits the envelope under ``input``/``patch``/``diff``
        # depending on the tool wiring. Try the well-known keys in
        # order — never raise.
        patch_body = (
            str(inputs.get("input", "") or "")
            or str(inputs.get("patch", "") or "")
            or str(inputs.get("diff", "") or "")
        )
        if patch_body:
            paths = parse_patch(patch_body)
            changed = paths.all_paths()

    return ToolEventRecord(
        tool_kind=kind,
        changed_paths=changed,
        command=command,
        patch_body=patch_body,
        tool_name=tool_name,
        session_id=session_id,
        tool_use_id=tool_use_id,
        turn_id=turn_id,
        cwd=cwd,
        project_dir=project_dir,
    )


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------

# Policy modules opt in to the in-process dispatch path by exposing a
# ``decide_for_record(record) -> Optional[PolicyDecision]`` callable.
# Modules without that callable are treated as no-ops (the harness
# adapter is expected to wire them via the existing JSON-stdin protocol
# at the harness layer). This avoids forcing a ``lint_*`` rewrite to
# land lane H.
_POLICY_HOOK_NAME = "decide_for_record"


def _resolve_policy_callable(module_id: str) -> Optional[Callable[..., Optional[PolicyDecision]]]:
    """Import ``module_id`` and return ``decide_for_record`` when present.

    Returns ``None`` when the module cannot be imported or when no hook
    is exported. Caller treats either as a no-op.
    """
    try:
        module = importlib.import_module(module_id)
    except Exception:
        return None
    func = getattr(module, _POLICY_HOOK_NAME, None)
    if not callable(func):
        return None
    return func


def dispatch(record: ToolEventRecord) -> PipelineResult:
    """Run ``record`` through its ordered policy chain.

    The chain is selected from :mod:`harness_hook_ordering` keyed on
    ``record.tool_kind``. For each module in the chain, if it exposes a
    ``decide_for_record`` callable, the dispatcher invokes it with the
    record. The first ``deny`` short-circuits the rest of the chain;
    ``allow`` and ``warn`` decisions accumulate.

    A module that raises is recorded as an ``error`` decision but does
    NOT short-circuit — the pipeline must remain fail-open in the face
    of buggy guards (per the existing PreToolUse hook contract).
    """
    result = PipelineResult()
    matcher = _TOOL_KIND_TO_MATCHER.get(record.tool_kind)
    if matcher is None:
        return result

    chain = ordered_pipeline_for("PreToolUse", matcher)
    for module_id in chain:
        callable_ = _resolve_policy_callable(module_id)
        if callable_ is None:
            # Module has no in-process policy hook — adapter handles it.
            continue

        try:
            decision = callable_(record)
        except Exception as exc:  # pragma: no cover - defensive
            result.decisions.append(
                PolicyDecision(
                    outcome="error",
                    reason=str(exc),
                    module=module_id,
                )
            )
            continue

        if decision is None:
            continue

        if not decision.module:
            decision.module = module_id

        result.decisions.append(decision)

        if decision.outcome == "deny":
            result.denied = True
            result.deny_reason = decision.reason
            result.deny_module = decision.module
            break

    return result
