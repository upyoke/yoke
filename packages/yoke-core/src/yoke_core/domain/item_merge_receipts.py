"""Typed access to one item's merge receipt from the machine that merges.

Every fact close-out needs afterwards — implementation and merge commits,
changed files, and observed post-push checks — belongs in this receipt. Once
the branch is contained by the target, ``merge-base`` returns the branch tip
and the diff that described its work collapses to nothing. The boundary
records the stable facts before cleanup so any retry converges without
depending on a lane that may already have been retired.

The receipt is stored with the item, in the ``item_sections`` document
:mod:`yoke_core.domain.item_merge_receipt_document` owns. That store lives on
the control plane, and the merge runs on the machine holding the checkout, so
these calls go through the registered ``merge_receipt.*`` functions rather
than opening a database a relayed control plane does not have locally.

An attempt that fails records that failure on the same entry, and a merge that
lands settles it. What a reader sees is the merge's current state, not a
chronology assembled from whatever telemetry survived.

Rationale for the boundary itself: ``docs/archive/decisions/
standalone-item-merge.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git

RECORD_FUNCTION_ID = "merge_receipt.record"
GET_FUNCTION_ID = "merge_receipt.get"


@dataclass(frozen=True)
class MergeReceipt:
    """The bookkeeping one merge of an item branch produced."""

    branch: str
    target: str
    commit_sha: str
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    check_runs: tuple[dict[str, str], ...] = field(default=())


def _call(function_id: str, item_id: int, payload: dict[str, Any]) -> Any:
    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload=payload,
    )


def _advisory(function_id: str, item_id: int, payload: dict[str, Any]) -> str:
    """Write through ``function_id``; return an advisory note, empty on success.

    Never raises and never unwinds a merge: a control-plane hiccup degrades
    crash recovery, and turning that into a refused merge would trade a rare
    recovery path for a common one. The note reaches the caller's warnings so
    the degradation is visible rather than silent.
    """
    try:
        response = _call(function_id, item_id, payload)
    except Exception as exc:  # noqa: BLE001 - advisory, never fatal
        return f"merge receipt not recorded: {exc}"
    if response.success:
        return ""
    detail = (
        response.error.message if response.error is not None
        else "receipt write failed"
    )
    return f"merge receipt not recorded: {detail}"


def record(item_id: int, receipt: MergeReceipt) -> str:
    """Persist ``receipt``. Returns an advisory message, empty on success.

    Fields that arrive empty leave whatever the entry already holds, so the
    pre-merge write and the completed write each contribute their own half.
    """
    return _advisory(
        RECORD_FUNCTION_ID,
        item_id,
        {
            "branch": receipt.branch,
            "target": receipt.target,
            "commit_sha": receipt.commit_sha,
            "merge_sha": receipt.merge_sha,
            "touched_files": list(receipt.touched_files),
            "check_runs": list(receipt.check_runs),
        },
    )


def record_failure(
    item_id: int,
    *,
    branch: str,
    target: str,
    label: str,
    phase: str = "",
    reason: str = "",
) -> str:
    """Record why this merge identity is currently failing."""
    return _advisory(
        RECORD_FUNCTION_ID,
        item_id,
        {
            "branch": branch,
            "target": target,
            "failure": {"label": label, "phase": phase, "reason": reason},
        },
    )


def record_settlement(item_id: int, *, branch: str, target: str) -> str:
    """Clear a recorded failure because this merge identity succeeded."""
    return _advisory(
        RECORD_FUNCTION_ID,
        item_id,
        {"branch": branch, "target": target, "settled": True},
    )


def load(item_id: int, branch: str, target: str) -> Optional[MergeReceipt]:
    """The receipt this item recorded for ``branch``/``target``."""
    try:
        response = _call(
            GET_FUNCTION_ID, item_id, {"branch": branch, "target": target},
        )
    except Exception:  # noqa: BLE001 - an unreachable store is "no receipt"
        return None
    if not response.success:
        return None
    entry = (response.result or {}).get("entry")
    if not isinstance(entry, dict):
        return None
    return MergeReceipt(
        branch=branch,
        target=target,
        commit_sha=str(entry.get("commit_sha") or ""),
        merge_sha=str(entry.get("merge_sha") or ""),
        touched_files=_clean(entry.get("touched_files")),
        check_runs=_clean_check_runs(entry.get("check_runs")),
    )


def _clean(paths: Any) -> tuple[str, ...]:
    if not isinstance(paths, (list, tuple)):
        return ()
    return tuple(str(path).strip() for path in paths if str(path).strip())


def _clean_check_runs(value: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    runs: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        run = {
            key: str(raw.get(key) or "").strip()
            for key in ("name", "status", "conclusion", "url")
        }
        if run["name"]:
            runs.append(run)
    return tuple(runs)


def landing_merge_commit(repo_root: str, target: str, commit_sha: str) -> str:
    """The merge commit that first carried ``commit_sha`` into ``target``.

    The last merge commit on the ancestry path is the oldest one that contains
    ``commit_sha``, so it is the candidate for the merge that landed the
    branch. A fast-forward leaves no merge commit behind and resolves to
    nothing — that case needs the receipt.

    A candidate only counts when its first parent does *not* already contain
    ``commit_sha``: carrying the commit in is what makes a merge the landing
    merge. A branch that never advanced past the base it forked from has a
    commit the target already contained, so every merge on the walk is
    somebody else's — answering with the oldest of them would attribute a
    neighbour's merge, and its whole diff, to this item.
    """
    if not commit_sha:
        return ""
    listing = git.git_out(
        repo_root,
        "rev-list", "--ancestry-path", "--merges", f"{commit_sha}..{target}",
    )
    merges = [line.strip() for line in listing.splitlines() if line.strip()]
    if not merges:
        return ""
    landed = merges[-1]
    if git.is_ancestor(repo_root, commit_sha, f"{landed}^1"):
        return ""
    return landed


def touched_files_from_merge_commit(
    repo_root: str, target: str, commit_sha: str,
) -> tuple[str, ...]:
    """What the merge that first contained ``commit_sha`` brought into ``target``.

    The landing merge's first-parent diff is exactly the branch's contribution.
    """
    landed = landing_merge_commit(repo_root, target, commit_sha)
    if not landed:
        return ()
    return _clean(
        git.git_out(
            repo_root, "diff", "--name-only", f"{landed}^1", landed,
        ).splitlines()
    )


def landed_merge_identity(
    *, item_id: int, branch: str, target: str, repo_root: str, already: bool,
    commit_sha: str,
) -> str:
    """The merge commit this branch actually landed on ``target``.

    A merge that just ran left the target tip pointing at its own merge
    commit, so the tip is the identity. When the branch was already contained
    on entry nothing landed now, and the tip is wherever the target has since
    moved — reading it there would hand this item whichever merge happened to
    be last. The branch's own landing merge answers instead, then the receipt
    a previous attempt recorded, and a branch that carried nothing in has no
    merge identity at all.
    """
    if not already:
        return git.git_out(repo_root, "rev-parse", target)
    landed = landing_merge_commit(repo_root, target, commit_sha)
    if landed:
        return landed
    recorded = load(item_id, branch, target)
    return recorded.merge_sha if recorded is not None else ""


def resolve_touched_files(
    *,
    repo_root: str,
    target: str,
    commit_sha: str,
    recorded: Optional[MergeReceipt],
    observed: Sequence[str],
) -> tuple[str, ...]:
    """The branch's changed-file set, never an already-merged empty diff.

    ``observed`` is the live ``merge-base``-relative diff, which is correct
    right up until the branch lands and empty from then on. Once it is empty
    the answer comes from the recorded merge identity — the receipt first,
    then the merge commit that carried the branch in.
    """
    if observed:
        return tuple(observed)
    if recorded is not None and recorded.touched_files:
        return recorded.touched_files
    return touched_files_from_merge_commit(repo_root, target, commit_sha)


__all__ = [
    "GET_FUNCTION_ID",
    "RECORD_FUNCTION_ID",
    "MergeReceipt",
    "landed_merge_identity",
    "landing_merge_commit",
    "load",
    "record",
    "record_failure",
    "record_settlement",
    "resolve_touched_files",
    "touched_files_from_merge_commit",
]
