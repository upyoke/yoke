"""Remote-evaluation controls + local-state policy classification.

``POST /v1/hooks/evaluate`` serves the same policy chains as the in-process
runner, but the server cannot see the CLIENT machine's filesystem, git
state, or process environment. Every chain policy is classified here, and
the https relay evaluates one chain split across the two sides:

- **server-safe** (not listed): the policy evaluates only the hook payload
  text and/or the control-plane DB — both available server-side — so it
  runs remotely as-is. The request's ``agent_type`` reaches payload-keyed
  detection (``lint_subagent_background``) via ``RunControls.payload_extra``.
- **client-evidenced authority**: ``lint_main_commit`` receives client Git
  facts in ``RunControls.payload_extra`` and then runs server-side so strategy
  docs and active-worktree authority stay DB-backed.
- **local-state** (``LOCAL_STATE_POLICIES``): the policy's verdict requires
  client-local evidence the server does not have. The relay client always
  evaluates its product-owned subset (``yoke_harness.hooks.local_subset``)
  BEFORE posting, and composes the verdicts — any deny wins, regardless of
  side. Server-side evaluation skips each one fail-OPEN with its module id
  recorded in the response's ``degraded`` list (the marker means "delegated
  to the client", not "protection off"). The client's eval roster is
  deliberately its own list — this SKIP list also covers server-unsafe
  chain members the client handles outside policy evaluation (e.g.
  ``session_dispatch``). None of these fail closed: each one's deny is
  contingent on *confirming* local facts (current branch, threatened
  uncommitted state, bound-workspace env, on-disk file content), and each
  already fails open by design when its probe is unavailable.

``RunControls`` is the runner-facing knob bundle: an injected total budget
(the remaining shared deadline), the skip classifier, payload augmentation,
the verified-token ``actor_id`` (server side), the ``flush_tail`` switch
(``False`` skips the telemetry/ensure-register tail), and result
write-backs (degraded markers, timeout flag, final outcome) callers need
but the ``(stdout, exit_code)`` return shape cannot carry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


__all__ = [
    "DEADLINE_EXHAUSTED_MARKER",
    "LOCAL_STATE_POLICIES",
    "RunControls",
    "remote_skip_marker",
]


# Policies whose verdict needs the CLIENT machine. One line of why each:
LOCAL_STATE_POLICIES: frozenset[str] = frozenset(
    {
        # Client env $YOKE_BOUND_WORKSPACE + client cwd comparison.
        "yoke_core.domain.lint_workspace_cwd_match",
        # `git -C <worktree> status` / stash inspection on the client FS.
        "yoke_core.domain.lint_destructive_git",
        # Walks the write target's parent dirs (.git / pyproject.toml).
        "yoke_core.domain.lint_python_runtime_import_in_tmp",
        # Reads the target file's content to count lines.
        "yoke_core.domain.hint_file_line_limit_approach",
        # Stray-DB detection scans the client repo root.
        "yoke_core.domain.db_error_hook",
        # Session orientation/lifecycle: hook-script-dir target resolution,
        # git subprocesses, client env mutation, bootstrap file reads.
        "runtime.harness.hook_runner.session_dispatch",
    }
)

# Appended to ``degraded`` when the propagated deadline expired before the
# chain finished. A deny computed before expiry is still rendered.
DEADLINE_EXHAUSTED_MARKER = "deadline_exhausted"


def remote_skip_marker(module_id: str) -> Optional[str]:
    """Server side of the split: skip local-state policies (client owns them)."""
    if module_id in LOCAL_STATE_POLICIES:
        return module_id
    return None


@dataclass
class RunControls:
    """Cross-boundary knobs for ``run_event`` (relay-split evaluation).

    ``budget_ms`` overrides the config-resolved total deadline with the
    caller's remaining shared budget. ``skip_module`` maps a module id
    to a degraded marker (skip) or ``None`` (run). ``payload_extra`` merges
    into the parsed payload before context build (e.g. the request's
    ``agent_type``). ``actor_id`` is the server-verified bearer-token actor
    bound at ensure-register. ``flush_tail=False`` skips the
    telemetry/ensure-register tail. ``degraded`` / ``timed_out`` /
    ``final_outcome`` are write-backs populated during the run.
    """

    budget_ms: Optional[int] = None
    skip_module: Optional[Callable[[str], Optional[str]]] = None
    payload_extra: dict[str, Any] = field(default_factory=dict)
    remote: bool = False
    actor_id: Optional[int] = None
    flush_tail: bool = True
    degraded: list[str] = field(default_factory=list)
    timed_out: bool = False
    final_outcome: str = ""
