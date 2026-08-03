"""Bind verification runs to the session's claim-bound worktree.

A verification run answers "does this tree pass?" — but until the tree is
named, a green says nothing about *which* tree passed. Two failure modes
converge here:

1. **Silent drift.** The harness re-applies a prior working directory
   between tool calls, so a session whose claimed lane is a linked
   worktree can find itself invoking pytest from the main checkout with
   no explicit ``cd`` in sight. pytest's positional collection resolves
   against the invocation directory, so the main tree is collected and
   the worktree's changes are never exercised. The existing
   out-of-checkout refusal in :mod:`yoke_core.tools._source_pythonpath`
   does not fire, because main *is* a legitimate checkout — just not the
   claimed one. The write-authority lint
   (:mod:`yoke_core.domain.lint_session_cwd`) does not fire either,
   because a test run is a read.

2. **Indistinguishable evidence.** A recorded green that carries no tree
   identity cannot be told apart from a green produced against the wrong
   tree, so the drift survives into the audit trail.

This module owns both answers. :func:`evaluate_tree_binding` is the pure
decision — refuse when the session holds claim-bound worktrees and the
run would execute outside all of them — and :func:`resolve_tree_identity`
names a tree by its root and HEAD sha so a run can record what it
actually verified.

An entry point covers only the invocations that reach it, so
:mod:`yoke_core.domain.verification_tree_binding_pytest_startup` hosts
the same decision at the layer pytest itself starts.

Session identity resolves through the canonical ambient chain
(:mod:`yoke_core.domain.session_ambient_identity`), not a bare
``YOKE_SESSION_ID`` read: harnesses that publish identity only through
the hook-written process-anchor registry would otherwise pass every
check by default, which is precisely the live configuration the drift
was observed in.

Both halves read through surfaces that follow the active connection.
Session identity resolves through the canonical ambient chain
(:mod:`yoke_core.domain.session_ambient_identity`), not a bare
``YOKE_SESSION_ID`` read, and claims resolve through the registered
``claims.work.holder_list`` function rather than a direct database
connection. Either shortcut answers only on a machine that happens to
hold identity in its environment and the control plane on its disk, and
silently answers "nothing to check" everywhere else — which is exactly
how a guard ends up inert on the installations it was written for.

Nothing here blocks a run it could not judge: an unresolvable session, a
checkout with no git metadata, or an unreachable control plane all let
the run proceed, because the check exists to catch drift, not to become
a new way for verification to be unavailable. But an unreachable lookup
returns a *notice* rather than silence, so "not verified" never again
looks identical to "verified clean".
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

#: Wrapper/CLI flag that runs a deliberate cross-tree verification.
ALLOW_TREE_MISMATCH_FLAG = "--allow-tree-mismatch"

TREE_BINDING_REFUSAL_TEMPLATE = (
    "{surface} TREE-BINDING REFUSAL: session {sid} holds an active "
    "work-claim with worktree '{wt}', but this run would execute in "
    "'{tree}', outside that worktree. Verification that runs in the wrong "
    "tree reports a green for code nobody changed.\n"
    "To verify the claimed worktree:\n"
    '  cd "{wt}"\n'
    f"and re-run, or pass {ALLOW_TREE_MISMATCH_FLAG} for a deliberate "
    "cross-tree run."
)

ALLOW_TREE_MISMATCH_NOTICE = (
    f"{{surface}}: {ALLOW_TREE_MISMATCH_FLAG} — verifying '{{tree}}' while "
    "the claimed worktree is '{wt}'."
)

UNVERIFIED_BINDING_NOTICE = (
    "{surface}: could not confirm '{tree}' is this session's claimed "
    "worktree — the control plane did not answer ({detail}). Proceeding "
    "unverified; if this run matters, confirm the tree yourself."
)


@dataclass(frozen=True)
class TreeIdentity:
    """Which tree a verification run executed against."""

    root: str
    head_sha: str

    def as_payload(self) -> dict[str, str]:
        """Serialize for evidence sections and QA run records."""
        return {"root": self.root, "head_sha": self.head_sha}


def _is_inside(target: str, root: str) -> bool:
    if not target or not root:
        return False
    try:
        resolved_target = str(Path(target).resolve())
        resolved_root = str(Path(root).resolve())
    except OSError:
        return False
    if resolved_target == resolved_root:
        return True
    return resolved_target.startswith(resolved_root + os.sep)


def _tree_is_free(tree: str) -> bool:
    """True when *tree* sits under the write lint's free-path allowlist.

    Read from :mod:`yoke_core.domain.lint_session_cwd_validate` so the
    verification backstop and the write lint agree on which temp
    directories pass through unconditionally.
    """
    try:
        from yoke_core.domain.lint_session_cwd_validate import (
            FREE_PATH_PREFIXES,
        )
    except Exception:
        return False
    try:
        resolved = str(Path(tree).resolve())
    except OSError:
        return False
    for prefix in FREE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def evaluate_tree_binding(
    tree: str,
    session_id: str,
    claim_worktrees: Sequence[str],
    *,
    surface: str,
) -> Optional[str]:
    """Pure decision — a remediation string, or ``None`` to proceed.

    Passes through for an empty session id, a session with no
    claim-bound worktrees (inline ``/yoke`` skill work and main-checkout
    source-dev both land here), a tree under the free-path allowlist, or
    a tree inside any claimed worktree.
    """
    if not session_id:
        return None
    worktrees = [str(path) for path in claim_worktrees if str(path).strip()]
    if not worktrees:
        return None
    if _tree_is_free(tree):
        return None
    for worktree in worktrees:
        if _is_inside(tree, worktree):
            return None
    return TREE_BINDING_REFUSAL_TEMPLATE.format(
        surface=surface, sid=session_id, wt=worktrees[0], tree=tree,
    )


@dataclass(frozen=True)
class ClaimLookup:
    """What the claim lookup found, and whether it could look at all.

    ``reachable=False`` means the control plane could not be consulted,
    which is emphatically not the same answer as "this session holds no
    claims" even though both yield an empty ``worktrees``. Collapsing
    the two is what let this guard sit inert: an unreachable lookup
    passed every run through while looking exactly like a clean one.
    """

    worktrees: tuple[str, ...] = ()
    reachable: bool = True
    detail: str = ""


def resolve_claim_worktrees(session_id: str) -> ClaimLookup:
    """Worktree lanes this session holds through active work claims.

    Goes through the registered ``claims.work.holder_list`` read, so the
    answer follows the active connection: relayed to the server over
    https, dispatched in process against a local universe. A direct
    database connection would answer only on a machine that happens to
    hold the control plane locally, and silently answer "no claims"
    everywhere else.
    """
    if not session_id:
        return ClaimLookup()
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="claims.work.holder_list",
            target=TargetRef(kind="global"),
            payload={"session_id": session_id},
        )
    except Exception as exc:
        return ClaimLookup(reachable=False, detail=str(exc) or type(exc).__name__)
    if not response.success:
        message = response.error.message if response.error else "lookup refused"
        return ClaimLookup(reachable=False, detail=message)
    holders = (response.result or {}).get("holders") or []
    lanes: list[str] = []
    for holder in holders:
        for path in holder.get("lane_worktrees") or []:
            candidate = str(path).strip()
            if candidate and candidate not in lanes:
                lanes.append(candidate)
    return ClaimLookup(worktrees=tuple(lanes))


def ambient_session_id() -> str:
    """The calling process's session id through the canonical chain.

    Env chain first, then the hook-written process-anchor registry. A
    bare ``YOKE_SESSION_ID`` read would miss every harness that publishes
    identity only through the registry.
    """
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        return (resolve_ambient_session_id() or "").strip()
    except Exception:
        return ""


@dataclass(frozen=True)
class TreeBindingVerdict:
    """What a caller should do about this run.

    ``refusal`` stops the run; ``notice`` is printed and the run
    proceeds. They are mutually exclusive.
    """

    refusal: Optional[str] = None
    notice: Optional[str] = None


def evaluate_run(
    *,
    surface: str,
    tree: Optional[str] = None,
    allow_mismatch: bool = False,
) -> TreeBindingVerdict:
    """Resolve session and claims, then judge *tree* (default: cwd).

    One lookup serves both the refusal and the override notice, so an
    overridden run costs no more control-plane traffic than a bound one.
    """
    session_id = ambient_session_id()
    if not session_id:
        return TreeBindingVerdict()
    target = tree if tree is not None else os.getcwd()
    if _tree_is_free(target):
        # Settled without consulting anything: a free-path tree passes
        # whatever the claims say, so asking would only add a round trip
        # to every run that happens to live under a temp root.
        return TreeBindingVerdict()
    lookup = resolve_claim_worktrees(session_id)
    if not lookup.reachable:
        # Proceeding is right — an unreachable control plane must not
        # ground every test run — but it is said out loud, because the
        # whole point of this guard is that an unverified run never
        # again reads like a verified one.
        return TreeBindingVerdict(
            notice=UNVERIFIED_BINDING_NOTICE.format(
                surface=surface, tree=target, detail=lookup.detail,
            )
        )
    if not lookup.worktrees:
        return TreeBindingVerdict()
    refusal = evaluate_tree_binding(
        target, session_id, lookup.worktrees, surface=surface,
    )
    if refusal is None:
        return TreeBindingVerdict()
    if allow_mismatch:
        return TreeBindingVerdict(
            notice=ALLOW_TREE_MISMATCH_NOTICE.format(
                surface=surface, tree=target, wt=lookup.worktrees[0],
            )
        )
    return TreeBindingVerdict(refusal=refusal)


def _git(args: Sequence[str], cwd: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def resolve_tree_identity(start: Optional[str | Path] = None) -> Optional[TreeIdentity]:
    """Name the tree at *start* by its root and HEAD sha.

    Returns ``None`` when *start* is not inside a git worktree or has no
    commits yet — a caller recording evidence should then say so rather
    than invent an identity.
    """
    cwd = str(Path(start).resolve()) if start is not None else os.getcwd()
    if not Path(cwd).is_dir():
        return None
    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return None
    head = _git(["rev-parse", "HEAD"], cwd)
    if head is None:
        return None
    return TreeIdentity(root=root, head_sha=head)


__all__ = [
    "ALLOW_TREE_MISMATCH_FLAG",
    "ALLOW_TREE_MISMATCH_NOTICE",
    "TREE_BINDING_REFUSAL_TEMPLATE",
    "UNVERIFIED_BINDING_NOTICE",
    "ClaimLookup",
    "TreeBindingVerdict",
    "TreeIdentity",
    "ambient_session_id",
    "evaluate_run",
    "evaluate_tree_binding",
    "resolve_claim_worktrees",
    "resolve_tree_identity",
]
