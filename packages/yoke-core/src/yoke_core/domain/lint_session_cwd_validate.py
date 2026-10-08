"""Per-tool-call claim-based validation for the session-cwd policy.

Authority comes from active work claims, project control planes, and free paths.
The slim hook-policy glue lives in :mod:`lint_session_cwd`. Behaviour:

* A write or state move into a lane another session holds is refused,
  whether or not the caller holds a claim. Reads of that lane are allowed.
* Read-only Git inspection of a lane → exempt from every test here.
* Read-shaped calls to ordinary home material and sanctioned installed paths
  use the executing machine's home. Project paths, dot-directories, and every
  write shape stay governed.
* Session with no claims → allowed everywhere except another session's
  live lane.
* Settled capacity operands inspect totals without granting content or mutation.
* Session with claims → other targets must land under a claimed worktree, a
  recorded project's control plane, or a free path.
* Bash with no extractable targets → the caller passes ``fallback_cwd``
  as a synthetic target so a worktree-binding session that runs a
  control-plane read from outside its worktree still validates against
  the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from yoke_contracts.free_paths import free_path_prefixes as machine_free_path_prefixes
from yoke_core.domain.lane_occupancy import LaneOccupant, occupying_claim
from yoke_core.domain.lint_session_cwd_control_plane import (
    is_under_yoke_control_plane,
)
from yoke_core.domain.lint_session_cwd_path_authority import (
    FREE_PATH_PREFIXES,
    TOOL_DIR_PREFIXES,
    derive_repo_roots as _derive_repo_roots,
    free_path_prefixes as _free_path_prefixes,
    recorded_repo_roots as _recorded_repo_roots,
    is_inside as _is_inside,
    is_inside_control_plane as _is_inside_control_plane,
    is_free_path as _path_is_free_path,
    is_under_tool_dir as _path_is_under_tool_dir,
    is_yoke_watcher_capture_path,
    resolve_for_display as _resolve_for_display,
)
from yoke_core.domain.lint_session_cwd_home import (
    is_external_reference_path,
    is_sanctioned_installed_read_path,
)
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    governed_targets,
    is_lane_mutation,
)
from yoke_core.domain.lint_session_cwd_status import (
    FAILURE_CLASS as _PRE_IMPL_FAILURE_CLASS,
    is_pre_implementing_status,
)
from yoke_core.domain.lint_session_cwd_identity import (
    FAILURE_CLASS as IDENTITY_FAILURE_CLASS,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)
from yoke_core.domain.lint_shell_path_use import PathUse, is_capacity_target
from yoke_core.domain.lint_session_cwd_item_lookup import (
    lookup_item_status,
    lookup_item_workflow,
)


SCOPE_FAILURE_CLASS = "scope_mismatch"
FOREIGN_LANE_FAILURE_CLASS = "foreign_lane"


@dataclass(frozen=True)
class ValidationVerdict:
    """Outcome of validating one tool call against session authority.

    ``allow=True`` means no deny payload. ``failure_class`` names the deny:
    ``scope_mismatch``, ``pre_implementing_status``, or ``foreign_lane``.
    The matching context fields are set on a deny.
    """

    allow: bool
    offending_target: str = ""
    claims: Sequence[ClaimedWorktree] = field(default_factory=tuple)
    repo_roots: Sequence[str] = field(default_factory=tuple)
    session_id: str = ""
    failure_class: str = SCOPE_FAILURE_CLASS
    matched_claim: Optional[ClaimedWorktree] = None
    item_status: Optional[str] = None
    occupant: Optional[LaneOccupant] = None


def validate_targets(
    conn: Any,
    *,
    session_id: str,
    targets: Sequence[str],
    fallback_cwd: str = "",
    watcher_capture_root: str = "",
    claude_job_tmp_root: str = "",
    machine_home: str | None = None,
    read_only: bool = False,
    command: str = "",
    tool_name: str = "",
    path_uses: tuple[PathUse, ...] = (),
) -> ValidationVerdict:
    """Validate every target path against the session's claim authority.

    ``targets`` is the list of extracted target paths for the tool call.
    Empty list means "no extracted targets" — the validator falls back
    to ``fallback_cwd`` as a synthetic target so the harness cwd still
    gets checked. ``fallback_cwd`` may be empty when the caller wants
    the no-target case to allow unconditionally (Edit/Read/Write always
    carry an explicit file_path target).
    Client-evidenced roots override local filesystem context on relayed calls.
    ``read_only`` admits explicitly sanctioned installed harness/tool paths.
    ``command`` is the Bash body, which decides the lane-inspection case.
    ``tool_name`` is the tool the call declared, which decides whether it has
    claimed to be a read at all.
    """
    if not (session_id or "").strip():
        return ValidationVerdict(
            allow=False,
            failure_class=IDENTITY_FAILURE_CLASS,
        )
    claims = claimed_worktrees(conn, session_id=session_id)
    repo_roots = tuple(_recorded_repo_roots(conn) or _derive_repo_roots(conn, claims))

    targets_to_check: List[str] = [
        t for t in targets if isinstance(t, str) and t.strip()
    ]
    if not targets_to_check and fallback_cwd.strip():
        targets_to_check = [fallback_cwd]

    targets_to_check = [
        raw for raw in targets_to_check if not is_capacity_target(raw, path_uses)
    ]

    targets_to_check = governed_targets(targets_to_check, repo_roots, command)
    # A read of a foreign lane is not a write, so it must not fail scope either.
    mutation = is_lane_mutation(tool_name, command)
    if not mutation:
        targets_to_check = [
            raw
            for raw in targets_to_check
            if occupying_claim(conn, target=raw, session_id=session_id) is None
        ]
    for raw in targets_to_check:
        occupant = occupying_claim(conn, target=raw, session_id=session_id)
        if occupant is not None:
            return ValidationVerdict(
                allow=False,
                offending_target=_resolve_for_display(raw),
                claims=claims,
                repo_roots=repo_roots,
                session_id=session_id,
                failure_class=FOREIGN_LANE_FAILURE_CLASS,
                occupant=occupant,
            )

    external_reads_allowed = read_only and _is_read_shaped(tool_name, command)

    if not session_id or not claims:
        return ValidationVerdict(
            allow=True,
            claims=claims,
            repo_roots=repo_roots,
            session_id=session_id,
        )

    for raw in targets_to_check:
        worktree_match = _matching_claim(raw, claims)
        if worktree_match is not None:
            # Target is inside a claimed worktree — the status gate applies
            # only to this branch. Control-plane and free-path targets stay
            # status-agnostic by design.
            status = lookup_item_status(conn, worktree_match.item_id)
            workflow = lookup_item_workflow(conn, worktree_match.item_id)
            if mutation and is_pre_implementing_status(workflow, status):
                return ValidationVerdict(
                    allow=False,
                    offending_target=_resolve_for_display(raw),
                    claims=claims,
                    repo_roots=repo_roots,
                    session_id=session_id,
                    failure_class=_PRE_IMPL_FAILURE_CLASS,
                    matched_claim=worktree_match,
                    item_status=status,
                )
            continue
        if _is_target_authorised(
            raw,
            claims=claims,
            repo_roots=repo_roots,
            session_id=session_id,
            watcher_capture_root=watcher_capture_root,
            claude_job_tmp_root=claude_job_tmp_root,
            machine_home=machine_home,
            read_only=read_only,
            external_reads_allowed=external_reads_allowed,
        ):
            continue
        return ValidationVerdict(
            allow=False,
            offending_target=_resolve_for_display(raw),
            claims=claims,
            repo_roots=repo_roots,
            session_id=session_id,
            failure_class=SCOPE_FAILURE_CLASS,
        )

    return ValidationVerdict(
        allow=True,
        claims=claims,
        repo_roots=repo_roots,
        session_id=session_id,
    )


def _is_read_shaped(tool_name: str, command: str) -> bool:
    """True when the call has positively declared itself a read.

    A body has to earn it from the shared read-only classifier, so a mixed
    read-and-mutate command, an output redirect, or a mutation chained onto a
    read never inherits a read's exemption. A call with no body qualifies on
    its tool alone, which the caller has already established is not a write —
    but only if it named one: a payload that never says which tool it is has
    claimed nothing, and absent evidence fails closed.
    """
    if not tool_name.strip():
        return False
    if command.strip():
        return match_read_only_signature(command) is not None
    return True


def _is_target_authorised(
    target: str,
    *,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
    session_id: str,
    watcher_capture_root: str,
    claude_job_tmp_root: str,
    machine_home: str | None,
    read_only: bool,
    external_reads_allowed: bool = False,
) -> bool:
    if _is_free_path(
        target,
        session_id=session_id,
        watcher_capture_root=watcher_capture_root,
        claude_job_tmp_root=claude_job_tmp_root,
        machine_home=machine_home,
    ):
        return True
    if _is_under_tool_dir(target):
        return True
    if read_only and is_sanctioned_installed_read_path(
        target,
        machine_home=machine_home,
    ):
        return True
    if external_reads_allowed and is_external_reference_path(
        target,
        repo_roots=repo_roots,
        machine_home=machine_home,
    ):
        return True
    for claim in claims:
        if _is_inside(target, claim.worktree_path):
            return True
    for root in repo_roots:
        if _is_inside_control_plane(target, root):
            return True
    # Yoke-control-plane carve-out: any active Yoke session may
    # read its own control plane (the Yoke main repo root, excluding
    # its ``.worktrees/`` subtree) regardless of which project's
    # worktree claim it currently holds. Sibling-branch worktrees stay
    # claim-gated through ``_is_inside_control_plane``'s `.worktrees`
    # exclusion.
    if is_under_yoke_control_plane(target):
        return True
    return False


def _is_free_path(
    target: str,
    *,
    session_id: str,
    watcher_capture_root: str,
    claude_job_tmp_root: str,
    machine_home: str | None,
) -> bool:
    # Keep the static roots monkeypatchable; add live TMPDIR at evaluation.
    prefixes = (
        machine_free_path_prefixes(FREE_PATH_PREFIXES)
        if machine_home is None
        else _free_path_prefixes(machine_home)
    )
    if _path_is_free_path(target, prefixes=prefixes, machine_home=machine_home):
        return True
    if claude_job_tmp_root and _is_inside(target, claude_job_tmp_root):
        return True
    return is_yoke_watcher_capture_path(
        target,
        scratch_root=watcher_capture_root or None,
        session_id=session_id,
    )


def _is_under_tool_dir(target: str) -> bool:
    return _path_is_under_tool_dir(target, prefixes=TOOL_DIR_PREFIXES)


def _matching_claim(
    target: str,
    claims: Sequence[ClaimedWorktree],
) -> Optional[ClaimedWorktree]:
    """Return the claim whose worktree contains ``target``, or ``None``.

    The lookup orders by claim insertion (matching ``claimed_worktrees``),
    so the first claim that covers the path wins. Free-path and
    control-plane targets are out of scope here — the caller checks
    them separately so the status gate fires only on the worktree
    branch.
    """
    for claim in claims:
        if _is_inside(target, claim.worktree_path):
            return claim
    return None


__all__ = [
    "FREE_PATH_PREFIXES",
    "SCOPE_FAILURE_CLASS",
    "TOOL_DIR_PREFIXES",
    "ValidationVerdict",
    "is_yoke_watcher_capture_path",
    "validate_targets",
]
