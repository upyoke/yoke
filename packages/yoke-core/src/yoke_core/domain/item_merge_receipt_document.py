"""The item-owned document carrying every merge receipt for one item.

A merge's bookkeeping has to outlive the things it describes. Once the branch
is contained by its target the engine deletes the branch ref and removes the
lane, and from then on ``merge-base`` reports an empty diff and the lane
directory is gone. Everything a retry, a terminal QA gate, a lane retirement,
or a release attribution still needs to know about that merge has to already
be written down somewhere cleanup does not reach.

That home is the item's own ``item_sections`` row — the same durable owner the
item's execution evidence uses — so a receipt lasts exactly as long as the item
does. Entries are keyed by the merge identity (branch and target), and one
merge writes its entry more than once: a pre-merge entry carrying the
implementation commit and changed files, then a completed entry carrying the
merge commit and the checks observed after the push. Each write folds into the
entry already stored, so a crash between the two still leaves the earlier facts
intact.

An entry also carries the merge's current failure, when the last attempt on
that identity failed. It is *current* rather than historical: a landed merge
settles it, so a reader sees the state the merge is in now instead of
reconstructing it from the order telemetry happened to arrive in.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_json_sections import read_json_section, upsert_json_section
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.schema_common import _table_exists

#: Section name and ordering of the receipt document on its item. The
#: ordering places it just after the execution evidence at 190.
MERGE_RECEIPTS_SECTION = "Merge Receipts"
MERGE_RECEIPTS_ORDERING = 195

_ENTRIES_KEY = "receipts"
#: Bounded so a stderr dump cannot grow the item document without limit.
_REASON_LIMIT = 1024


def entry_key(branch: str, target: str) -> str:
    """The merge identity one entry is stored under."""
    return f"{branch}::{target}"


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _entries(document: Optional[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    raw = (document or {}).get(_ENTRIES_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): dict(value)
        for key, value in raw.items()
        if isinstance(value, Mapping)
    }


def read_entries(conn: Any, item_id: int) -> dict[str, dict[str, Any]]:
    """Every merge entry recorded on ``item_id``, keyed by merge identity."""
    return _entries(
        read_json_section(
            conn, item_id=int(item_id), section=MERGE_RECEIPTS_SECTION
        )
    )


def newest_first(
    entries: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Entries ordered newest write first.

    The document is stored with sorted keys so JSON diffs stay readable, which
    means insertion order does not survive a round trip. ``updated_at`` is the
    order that does.
    """
    return sorted(
        (dict(entry) for entry in entries.values()),
        key=lambda entry: str(entry.get("updated_at") or ""),
        reverse=True,
    )


def _clean_paths(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_check_runs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)):
        return []
    runs: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        run = {
            key: str(raw.get(key) or "").strip()
            for key in ("name", "status", "conclusion", "url")
        }
        if run["name"]:
            runs.append(run)
    return runs


def build_failure(
    *, label: str, phase: str = "", reason: str = "",
) -> dict[str, str]:
    """One merge attempt's failure, as the document stores it."""
    return {
        "label": str(label or "merge failed").strip() or "merge failed",
        "phase": str(phase or "").strip(),
        "reason": str(reason or "").strip()[:_REASON_LIMIT],
        "recorded_at": iso8601_now(),
    }


def record_entry(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    target: str,
    commit_sha: str = "",
    merge_sha: str = "",
    touched_files: Sequence[str] = (),
    check_runs: Sequence[Mapping[str, Any]] = (),
    failure: Optional[Mapping[str, Any]] = None,
    settled: bool = False,
) -> dict[str, Any]:
    """Fold one merge's facts into its entry and return the stored entry.

    A value that arrives empty leaves whatever the entry already held: the
    pre-merge write carries no merge commit, and the completed write carries
    no changed files, so neither may erase the other's contribution.

    A landed merge settles the identity. ``merge_sha`` and an explicit
    ``settled`` both drop the recorded failure, because a merge that finished
    is not a merge that is currently failing.
    """
    entries = read_entries(conn, item_id)
    key = entry_key(branch, target)
    entry = dict(entries.get(key) or {})
    entry["branch"] = branch
    entry["target"] = target
    entry["commit_sha"] = str(commit_sha or entry.get("commit_sha") or "")
    entry["merge_sha"] = str(merge_sha or entry.get("merge_sha") or "")
    entry["touched_files"] = (
        _clean_paths(touched_files) or _clean_paths(entry.get("touched_files"))
    )
    entry["check_runs"] = (
        _clean_check_runs(check_runs) or _clean_check_runs(entry.get("check_runs"))
    )
    if settled or entry["merge_sha"]:
        entry.pop("failure", None)
    elif failure is not None:
        entry["failure"] = dict(failure)
    entry["updated_at"] = iso8601_now()
    entries[key] = entry
    upsert_json_section(
        conn,
        item_id=int(item_id),
        section=MERGE_RECEIPTS_SECTION,
        payload={_ENTRIES_KEY: entries},
        ordering=MERGE_RECEIPTS_ORDERING,
    )
    return entry


def find_entry(
    conn: Any, item_id: int, *, branch: str, target: str = "",
) -> Optional[dict[str, Any]]:
    """The newest entry for ``branch``, narrowed to ``target`` when given.

    Lane retirement knows the branch a lane recorded but not the target it
    landed on, so an empty ``target`` matches any target for that branch.
    """
    for entry in newest_first(read_entries(conn, item_id)):
        if str(entry.get("branch") or "") != branch:
            continue
        if target and str(entry.get("target") or "") != target:
            continue
        return entry
    return None


def landing_shas(conn: Any, item_id: int) -> list[str]:
    """The implementation and merge commits this item's newest receipt names."""
    commit_sha = ""
    merge_sha = ""
    for entry in newest_first(read_entries(conn, item_id)):
        commit_sha = commit_sha or str(entry.get("commit_sha") or "").strip()
        merge_sha = merge_sha or str(entry.get("merge_sha") or "").strip()
    return [commit_sha, merge_sha]


def _documents_for(
    conn: Any, sql: str, params: Sequence[Any],
) -> list[tuple[int, dict[str, dict[str, Any]]]]:
    documents: list[tuple[int, dict[str, dict[str, Any]]]] = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        item_id = int(row["item_id"] if hasattr(row, "keys") else row[0])
        raw = row["content"] if hasattr(row, "keys") else row[1]
        try:
            parsed = loads_text(str(raw))
        except (TypeError, ValueError):
            continue
        entries = _entries(parsed if isinstance(parsed, Mapping) else None)
        if entries:
            documents.append((item_id, entries))
    return documents


def current_failures(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """The label of each item's current merge failure, when it has one.

    An identity whose merge landed carries no failure, so an item shows up
    here only while a merge attempt on it is unresolved.
    """
    if not item_ids or not _table_exists(conn, "item_sections"):
        return {}
    marker = _placeholder(conn)
    sql = (
        "SELECT item_id,content FROM item_sections "
        "WHERE section_name = " + marker + " AND item_id IN ("
        + ",".join(marker for _ in item_ids)
        + ")"
    )
    failures: dict[int, str] = {}
    for item_id, entries in _documents_for(
        conn, sql, (MERGE_RECEIPTS_SECTION, *(int(i) for i in item_ids))
    ):
        for entry in newest_first(entries):
            failure = entry.get("failure")
            if isinstance(failure, Mapping):
                failures[item_id] = str(failure.get("label") or "merge failed")
                break
    return failures


def merge_identities(
    conn: Any, project_id: int,
) -> Iterable[tuple[int, str]]:
    """Every ``(item_id, sha)`` this project's receipts recorded.

    Both the merge commit and the implementation commit are yielded: a release
    range may contain either, and only the receipt binds them to the item.
    """
    marker = _placeholder(conn)
    sql = (
        "SELECT s.item_id,s.content FROM item_sections s "
        "JOIN items i ON i.id = s.item_id "
        "WHERE i.project_id = " + marker + " AND s.section_name = " + marker
    )
    for item_id, entries in _documents_for(
        conn, sql, (int(project_id), MERGE_RECEIPTS_SECTION)
    ):
        for entry in entries.values():
            for field in ("merge_sha", "commit_sha"):
                sha = str(entry.get(field) or "").strip()
                if sha:
                    yield item_id, sha


__all__ = [
    "MERGE_RECEIPTS_ORDERING",
    "MERGE_RECEIPTS_SECTION",
    "build_failure",
    "current_failures",
    "entry_key",
    "find_entry",
    "landing_shas",
    "merge_identities",
    "newest_first",
    "read_entries",
    "record_entry",
]
