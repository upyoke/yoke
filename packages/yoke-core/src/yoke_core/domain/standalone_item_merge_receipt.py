"""Durable bookkeeping for one standalone merge, written before cleanup.

Every fact close-out needs afterwards — implementation and merge commits,
changed files, and observed post-push checks — belongs in this receipt. Once
the branch is contained by the target, ``merge-base`` returns the branch tip
and the diff that described its work collapses to nothing. The boundary
records the stable facts here so any retry converges without depending on a
lane that may already have been retired.

The receipt rides the events ledger: durable, relayed over both transports
through the dispatcher, and needing no storage of its own. Writing it before
the merge also warms the dispatch path the close-out reuses — in-process, that
is the registry's whole import-time handler catalog — so the close-out never
has to resolve a module for the first time out of a lane that is already gone.

Rationale for the boundary itself: ``docs/archive/decisions/
standalone-item-merge.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.json_helper import loads_text

RECEIPT_EVENT_NAME = "StandaloneMergeReceiptRecorded"

# How far back to look for this item's receipts. A single merge writes two
# rows (one before the engine runs, one once the merge identity is known);
# the window is generous enough to survive repeated retries of the same item.
_RECEIPT_LOOKBACK = 50


@dataclass(frozen=True)
class MergeReceipt:
    """The bookkeeping one standalone merge produced."""

    branch: str
    target: str
    commit_sha: str
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    check_runs: tuple[dict[str, str], ...] = field(default=())


def _emit_receipt_event(
    *, name: str, item_id: int, project: str, context: dict[str, Any],
) -> Any:
    """Write one receipt row to the ledger through the dispatcher.

    Named for what it is so the event-registry discovery scan recognizes it as
    an emitter call site and registers ``name`` without a hand-authored data
    row.
    """
    return call_dispatcher(
        function_id="events.emit",
        target=TargetRef(kind="global"),
        payload={
            "name": name,
            "kind": "lifecycle",
            "type": "merge_lifecycle",
            "source_type": "system",
            "severity": "INFO",
            "outcome": "success",
            "project": project,
            "item_id": str(int(item_id)),
            "context": context,
        },
    )


def record(item_id: int, receipt: MergeReceipt, *, project: str) -> str:
    """Persist ``receipt``. Returns an advisory message, empty on success.

    ``project`` is the owning item's project slug: ``events.emit`` is a
    project-scoped function over the dispatcher, so an empty project is
    refused and the receipt would be silently skipped.

    Never raises and never unwinds a merge: a ledger hiccup degrades crash
    recovery, and turning that into a refused merge would trade a rare
    recovery path for a common one.
    """
    try:
        response = _emit_receipt_event(
            name=RECEIPT_EVENT_NAME,
            item_id=item_id,
            project=project,
            context={
                "branch": receipt.branch,
                "target": receipt.target,
                "commit_sha": receipt.commit_sha,
                "merge_sha": receipt.merge_sha,
                "touched_files": list(receipt.touched_files),
                "check_runs": list(receipt.check_runs),
            },
        )
    except Exception as exc:  # noqa: BLE001 - advisory, never fatal
        return f"merge receipt not recorded: {exc}"
    if response.success:
        return ""
    detail = (
        response.error.message if response.error is not None
        else "receipt write failed"
    )
    return f"merge receipt not recorded: {detail}"


def _context(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("envelope")
    try:
        envelope = loads_text(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    context = envelope.get("context") if isinstance(envelope, dict) else None
    return context if isinstance(context, dict) else {}


def load(
    item_id: int, branch: str, target: str, *, project: str,
) -> Optional[MergeReceipt]:
    """The most complete receipt this item recorded for ``branch``/``target``.

    One merge writes a pre-merge row and a completed row, so the fields are
    folded newest-first: the newest non-empty value for each field wins, and a
    crash between the two rows still yields the commit and touched-file facts
    the earlier row already carried.
    """
    try:
        response = call_dispatcher(
            function_id="events.query.run",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={
                "event_name": RECEIPT_EVENT_NAME,
                "project": project,
                "limit": _RECEIPT_LOOKBACK,
            },
        )
    except Exception:  # noqa: BLE001 - an unreadable ledger is "no receipt"
        return None
    if not response.success:
        return None

    commit_sha = ""
    merge_sha = ""
    touched: tuple[str, ...] = ()
    check_runs: tuple[dict[str, str], ...] = ()
    found = False
    for row in (response.result or {}).get("rows") or []:
        context = _context(row if isinstance(row, dict) else {})
        if context.get("branch") != branch or context.get("target") != target:
            continue
        found = True
        commit_sha = commit_sha or str(context.get("commit_sha") or "")
        merge_sha = merge_sha or str(context.get("merge_sha") or "")
        touched = touched or _clean(context.get("touched_files"))
        check_runs = check_runs or _clean_check_runs(context.get("check_runs"))
    if not found:
        return None
    return MergeReceipt(
        branch=branch,
        target=target,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        touched_files=touched,
        check_runs=check_runs,
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
    ``commit_sha``, so it is the merge that landed the branch. A fast-forward
    leaves no merge commit behind and resolves to nothing — that case needs the
    receipt.
    """
    if not commit_sha:
        return ""
    listing = git.git_out(
        repo_root,
        "rev-list", "--ancestry-path", "--merges", f"{commit_sha}..{target}",
    )
    merges = [line.strip() for line in listing.splitlines() if line.strip()]
    return merges[-1] if merges else ""


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
    "MergeReceipt",
    "RECEIPT_EVENT_NAME",
    "landing_merge_commit",
    "load",
    "record",
    "resolve_touched_files",
    "touched_files_from_merge_commit",
]
