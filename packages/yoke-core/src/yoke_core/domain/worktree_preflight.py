"""Harness-universal advance implementation-entry preflight primitive.

Owns the operator-required steps for ``/yoke advance YOK-N
implementation``: (1) resolve/acquire work claim, (2) activate/
reconcile path claim, (3) resolve or create the item worktree
(canonical ``YOK-N``), (4) record the descriptive worktree/cwd relationship,
(5) return a machine-readable envelope with ``item_id``, ``branch``,
``worktree_path``, ``semantic_scope`` (descriptive label only), and
``physical_cwd_mode`` (``matched`` when harness cwd is inside the
worktree; ``static`` when it stayed in main).

The session's write authority over the new worktree comes from its
active ``work_claims`` row, validated per tool call by
``lint_session_cwd``. The preflight no longer binds a session-scope
envelope, and no ``scope:entered`` action is emitted.

Dirty-main guard runs only when creating a new worktree — re-entry
does not touch main. Errors surface as ``ok=False`` outcomes with a
``block_kind`` and rendered ``narrative``. CLI: exit 0 (envelope to
stdout), exit 1 (sanctioned block, narrative to stderr), exit 2
(usage / bad-input).

Step helpers live in :mod:`yoke_core.domain.worktree_preflight_steps`
so the orchestrator + CLI stay under the 350-line authored-file cap.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_core.domain.worktree_paths import _normalize_repo_root
from yoke_core.domain.worktree_preflight_steps import (
    BLOCK_CREATE_FAILED,
    BLOCK_DB_LOCK,
    BLOCK_DIRTY_TRACKED,
    BLOCK_INPUT,
    BLOCK_PATH_CLAIM,
    BLOCK_WORK_CLAIM,
    CWD_MODE_STATIC,
    activate_path_claims,
    check_dirty_main,
    claim_work,
    classify_activation_failure,
    extract_retry_attempts,
    physical_cwd_mode,
)


@dataclass
class WorktreePreflightOutcome:
    """Structured outcome. ``ok`` distinguishes envelope vs block."""

    ok: bool = True
    block_kind: str = ""
    narrative: str = ""
    item_id: int = 0
    branch: str = ""
    worktree_path: str = ""
    semantic_scope: str = "main"
    physical_cwd_mode: str = ""
    actions_taken: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_envelope(self) -> Dict[str, Any]:
        """Serialise as the operator-defined execution envelope."""
        if not self.ok:
            return {
                "ok": False,
                "block_kind": self.block_kind,
                "narrative": self.narrative,
                "item_id": self.item_id,
            }
        return {
            "ok": True,
            "item_id": self.item_id,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "semantic_scope": self.semantic_scope,
            "physical_cwd_mode": self.physical_cwd_mode,
            "actions_taken": list(self.actions_taken),
            "notes": list(self.notes),
        }


def run_preflight(
    *,
    item_id: int,
    project: Optional[str] = None,
    repo_root: Optional[str] = None,
    session_id: str = "",
    actual_cwd: str = "",
    no_worktree: bool = False,
) -> WorktreePreflightOutcome:
    """Run the harness-universal advance implementation-entry preflight."""
    branch = f"YOK-{item_id}"
    out = WorktreePreflightOutcome(item_id=item_id, branch=branch)

    if repo_root is None:
        from yoke_core.domain.worktree_paths import (
            _resolve_repo_root_from_cwd,
        )
        if project:
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.project_checkout_locations import checkout_for_project

            with connect() as conn:
                checkout = checkout_for_project(conn, project)
            repo_root = str(checkout) if checkout is not None else ""
        else:
            repo_root = _resolve_repo_root_from_cwd()
    repo_root = _normalize_repo_root(repo_root or "") or ""
    if not repo_root:
        out.ok = False
        out.block_kind = BLOCK_INPUT
        out.narrative = "Could not resolve repo root for preflight."
        return out

    # Step 0 — items.blocked refusal. Fires before claim
    # acquisition so an operator-blocked item never silently grabs the work
    # claim only to be refused later. The pre-commit worktree-status guard
    # is unchanged because blocked is a routing hold, not a filesystem hold.
    try:
        from yoke_core.domain.advance_blocked_gate import evaluate as _eval_blocked
        from yoke_core.domain.db_helpers import connect as _connect_db
        _conn = _connect_db()
        try:
            decision = _eval_blocked(_conn, item_id)
        finally:
            _conn.close()
        if decision.blocked:
            out.ok = False
            out.block_kind = "blocked-flag"
            out.narrative = decision.rendered_blocker or (
                f"YOK-{item_id} has items.blocked=1; run /yoke unblock YOK-{item_id} first."
            )
            return out
    except Exception:  # noqa: BLE001 - degrade if DB unavailable
        pass

    # Step 1 — work claim.
    ok, claim_msg = claim_work(item_id)
    if not ok:
        out.ok = False
        out.block_kind = BLOCK_WORK_CLAIM
        out.narrative = (
            f"Could not acquire work claim for YOK-{item_id}: {claim_msg}\n"
            "If another live session holds the claim, coordinate or wait. "
            "The remediation is NOT to widen a path claim — work-claim "
            "ownership and path-claim coverage are different invariants."
        )
        return out
    out.actions_taken.append(
        "work-claim:already-owned"
        if "already" in claim_msg.lower()
        else "work-claim:acquired"
    )

    # Step 2 — path-claim activation. Substrate DB-lock contention is
    # classified distinctly from upstream coordination failures so the
    # narrative routes the operator to the right remediation.
    pc_ok, pc_err, activated_ids = activate_path_claims(item_id)
    if not pc_ok:
        out.ok = False
        out.block_kind = classify_activation_failure(pc_err)
        if out.block_kind == BLOCK_DB_LOCK:
            attempts = extract_retry_attempts(pc_err)
            attempt_count = attempts if attempts is not None else 1
            out.narrative = (
                f"DB lock contention on path-snapshot materialization, "
                f"retried {attempt_count} times — substrate friction, "
                "not coordination."
            )
        else:
            out.narrative = (
                f"Path-claim activation blocked for YOK-{item_id}:\n{pc_err}\n"
                "Wait for the upstream coordination to clear, or reconcile "
                "diverged refs (`git push` / `git pull` / `git rebase`)."
            )
        return out
    out.actions_taken.append(
        f"path-claim:activated={activated_ids}"
        if activated_ids
        else "path-claim:no-op"
    )

    # Step 3 — worktree resolution / creation.
    if no_worktree:
        out.actions_taken.append("worktree:skipped")
    else:
        worktrees_dir = os.path.join(repo_root, ".worktrees")
        canonical_path = os.path.join(worktrees_dir, branch)
        canonical_exists = os.path.isdir(canonical_path)
        will_create = not canonical_exists
        if will_create:
            blocked, kind, paths = check_dirty_main(repo_root)
            if blocked:
                out.ok = False
                out.block_kind = kind
                listing = "\n  - ".join(paths[:20])
                if len(paths) > 20:
                    listing += f"\n  - ... +{len(paths) - 20} more"
                kind_label = (
                    "tracked or staged"
                    if kind == BLOCK_DIRTY_TRACKED
                    else "untracked, non-gitignored"
                )
                out.narrative = (
                    f"Cannot create worktree for YOK-{item_id}: main has "
                    f"{kind_label} files. Commit, stash, remove, or "
                    f"gitignore them and retry.\n  - {listing}"
                )
                return out
        # Direct import: a test patching `worktree_cli.create_worktree`
        # does NOT cover this call site. Patch `worktree_create.create_worktree`
        # (or scope `repo_root` to a tempdir) to keep tests off the real repo.
        from yoke_core.domain.worktree_create import create_worktree
        create_result = create_worktree(
            item_id=item_id,
            project=project,
            repo_root=repo_root,
        )
        if create_result.error:
            out.ok = False
            out.block_kind = BLOCK_CREATE_FAILED
            out.narrative = f"create_worktree failed: {create_result.error}"
            return out
        out.worktree_path = create_result.path
        out.actions_taken.append(
            "worktree:created" if create_result.created else "worktree:reused"
        )

    # Step 4 — record cwd-vs-worktree relationship for the operator envelope.
    # The session's write authority over the new worktree comes from its
    # active work-claim (validated per-call by lint_session_cwd), not from
    # a scope envelope. ``semantic_scope`` here is a descriptive label for
    # the consumer's envelope output, not an authority record.
    out.semantic_scope = "main" if no_worktree else "worktree"

    # Step 5 — physical cwd info for the operator envelope.
    if not no_worktree and out.worktree_path:
        actual = actual_cwd or os.getcwd()
        out.physical_cwd_mode = physical_cwd_mode(actual, out.worktree_path)
        if out.physical_cwd_mode == CWD_MODE_STATIC:
            out.notes.append(
                "Harness cwd remained at main while the worktree is at "
                f"{out.worktree_path}. Use absolute paths or `git -C "
                f"{out.worktree_path}` for worktree-targeting tool calls."
            )
    return out


def _parse_item_id(value: str) -> int:
    raw = value.strip()
    for prefix in ("YOK-", "yok-"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    raw = raw.lstrip("0") or "0"
    return int(raw)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.worktree_preflight",
        description="Harness-universal /yoke advance worktree re-entry primitive.",
    )
    parser.add_argument("--item", required=True, help="YOK-N or numeric item id")
    parser.add_argument("--project", default=None)
    parser.add_argument("--no-worktree", action="store_true")
    parser.add_argument(
        "--session-id",
        default=os.environ.get("YOKE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or "",
    )
    args = parser.parse_args(argv)
    try:
        item_id = _parse_item_id(args.item)
    except (TypeError, ValueError):
        print(f"Invalid --item: {args.item!r}", file=sys.stderr)
        return 2
    outcome = run_preflight(
        item_id=item_id,
        project=args.project,
        session_id=args.session_id,
        actual_cwd=os.getcwd(),
        no_worktree=args.no_worktree,
    )
    print(json.dumps(outcome.to_envelope(), indent=2))
    if outcome.ok:
        return 0
    print(outcome.narrative, file=sys.stderr)
    return 1


__all__ = [
    "WorktreePreflightOutcome",
    "main",
    "run_preflight",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
