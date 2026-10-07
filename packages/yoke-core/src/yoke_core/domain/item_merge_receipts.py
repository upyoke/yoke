"""Persist and read exact-commit merge recovery receipts.

Receipt writes are advisory: a transport refusal is reported without
unwinding the merge. All transport calls name items by their public ref."""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import item_merge_contributed_commits as contributed
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
    #: The item's own first-parent commits this landing put on ``target``
    #: (:mod:`yoke_core.domain.item_merge_contributed_commits`).
    contributed_commits: tuple[str, ...] = field(default=())


def _call(function_id: str, item_id: int, payload: dict[str, Any]) -> Any:
    return call_dispatcher(
        function_id=function_id,
        target=public_item_target(item_id),
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
        response.error.message if response.error is not None else "receipt write failed"
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
            "contributed_commits": list(receipt.contributed_commits),
        },
    )


def record_before_landing(
    item_id: int,
    *,
    repo_root: str,
    branch: str,
    target: str,
    commit_sha: str,
    touched_files: Sequence[str],
) -> str:
    """The pre-merge write: the lane head, its files, and what it contributes.

    Only before the merge does ``target`` still say where the contribution
    starts; a fast forward erases that boundary, so the set is taken now.
    """
    return record(
        item_id,
        MergeReceipt(
            branch=branch,
            target=target,
            commit_sha=commit_sha,
            touched_files=tuple(touched_files),
            contributed_commits=contributed.before_landing(
                repo_root,
                target=target,
                commit_sha=commit_sha,
            ),
        ),
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
            GET_FUNCTION_ID,
            item_id,
            {"branch": branch, "target": target},
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
        contributed_commits=_clean(entry.get("contributed_commits")),
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
    """The merge on ``target``'s trunk that first carried ``commit_sha``.

    Resolved on ``target``'s own first-parent chain, because that chain is
    what the base actually took. A branch can become an ancestor of
    ``target`` without its own merge ever joining that chain: a later "merge
    origin/main into <branch>" absorbs the earlier merge as a second parent,
    and some other commit lands the result. Walking plain ancestry answered
    with that absorbed merge, which dated the item to a landing the trunk
    never took -- an item whose branch landed twice kept the first, superseded
    answer.

    Containment along a first-parent chain is monotonic: once a commit on it
    holds ``commit_sha``, every newer one does. So the boundary between the
    two is found by bisecting rather than by testing each commit.

    The boundary narrows the search; it does not answer the question. A
    branch that never advanced past the trunk commit it forked from has a
    ``commit_sha`` already ON the chain, so every commit after it holds one
    the trunk always had, and the boundary is simply whatever landed next --
    a neighbour's merge. The candidate's own first parent is what tells them
    apart: when it already holds ``commit_sha``, the candidate carried
    nothing in and this branch has no landing merge of its own.

    A fast-forward leaves no merge commit behind and resolves to nothing --
    that case needs the receipt.
    """
    if not commit_sha:
        return ""
    listing = git.git_out(
        repo_root,
        "rev-list",
        "--first-parent",
        f"{commit_sha}..{target}",
    )
    chain = [line.strip() for line in listing.splitlines() if line.strip()]
    if not chain:
        return ""
    # chain runs newest to oldest; bisect for the oldest commit holding it.
    low, high, landed = 0, len(chain) - 1, ""
    while low <= high:
        middle = (low + high) // 2
        if git.is_ancestor(repo_root, commit_sha, chain[middle]):
            landed = chain[middle]
            low = middle + 1
        else:
            high = middle - 1
    if not landed or not _is_merge(repo_root, landed):
        return ""
    if git.is_ancestor(repo_root, commit_sha, f"{landed}^1"):
        return ""
    return landed


def _is_merge(repo_root: str, commit: str) -> bool:
    """Whether ``commit`` has more than one parent."""
    parents = git.git_out(repo_root, "rev-list", "-1", "--parents", commit)
    return len(parents.split()) > 2


def touched_files_from_merge_commit(
    repo_root: str,
    target: str,
    commit_sha: str,
) -> tuple[str, ...]:
    """What the merge that first contained ``commit_sha`` brought into ``target``.

    The landing merge's first-parent diff is exactly the branch's contribution.
    """
    landed = landing_merge_commit(repo_root, target, commit_sha)
    if not landed:
        return ()
    return _clean(
        git.git_out(
            repo_root,
            "diff",
            "--name-only",
            f"{landed}^1",
            landed,
        ).splitlines()
    )


def landed_merge_identity(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    already: bool,
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
    "record_before_landing",
    "record_failure",
    "record_settlement",
    "resolve_touched_files",
    "touched_files_from_merge_commit",
]
