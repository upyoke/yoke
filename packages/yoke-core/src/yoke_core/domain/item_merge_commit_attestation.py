"""Attest commits to an item whose merge receipt landed without them.

A landing records the commits it contributed, and release attribution credits
exactly those. A receipt written by a build that did not yet record them, or
by a landing that left no boundary to derive them from, names only its
implementation and merge commits — and a release carrying the rest refuses
them as unattributed. They are the item's work all the same, so the repair is
to say so on the item's own receipt, never to waive them on the run.

An attestation is recorded beside the derived set rather than folded into it,
with the reason the operator gave, so a reader can always tell what the merge
derived from what a person asserted afterwards.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from yoke_core.domain import item_merge_receipt_document as document
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_json_sections import upsert_json_section

_FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class CommitAttestationRefused(ValueError):
    """An attestation that cannot be recorded, with its named reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _full_shas(commits: Sequence[str]) -> list[str]:
    shas = [str(commit or "").strip().lower() for commit in commits]
    short = [sha for sha in shas if not _FULL_SHA.fullmatch(sha)]
    if short or not shas:
        raise CommitAttestationRefused(
            "commit_sha_not_full",
            "attest full commit SHAs only, exactly as the release refusal "
            f"printed them; not a full SHA: {', '.join(short) or '(none given)'}. "
            "Resolve one with `git -C <checkout> rev-parse <ref>`.",
        )
    return list(dict.fromkeys(shas))


def _recorded_shas(entry: dict[str, Any]) -> set[str]:
    shas = {
        str(entry.get(key) or "").strip().lower()
        for key in ("commit_sha", "merge_sha")
    }
    shas |= {str(sha).strip().lower() for sha in entry.get("contributed_commits") or []}
    shas |= {
        str(attested.get("commit_sha") or "").strip().lower()
        for attested in entry.get(document.ATTESTED_COMMITS_KEY) or []
        if isinstance(attested, dict)
    }
    return shas - {""}


def attest_commits(
    conn: Any, *, item_id: int, commits: Sequence[str], reason: str,
) -> dict[str, Any]:
    """Record ``commits`` as ``item_id``'s on its newest landed receipt entry.

    Refuses a short SHA, an empty reason, and an item with no landed receipt:
    an attestation names a landing that already happened, so an item that
    never merged has nothing to attach one to. A commit the entry already
    names is reported rather than recorded twice.
    """
    shas = _full_shas(commits)
    reason = str(reason or "").strip()
    if not reason:
        raise CommitAttestationRefused(
            "reason_required",
            "say why these commits are this item's work: --reason TEXT",
        )
    entries = document.read_entries(conn, int(item_id))
    landed = [
        entry for entry in document.newest_first(entries)
        if str(entry.get("merge_sha") or "").strip()
    ]
    if not landed:
        raise CommitAttestationRefused(
            "no_landed_receipt",
            f"item {item_id} has no merge receipt naming a landed merge, so "
            "there is no landing to attest these commits to. Land the item "
            "through `yoke merge item`, or attest them to the item that did.",
        )
    entry = landed[0]
    already = _recorded_shas(entry)
    added = [sha for sha in shas if sha not in already]
    recorded_at = iso8601_now()
    entry[document.ATTESTED_COMMITS_KEY] = [
        *(entry.get(document.ATTESTED_COMMITS_KEY) or []),
        *(
            {"commit_sha": sha, "reason": reason, "recorded_at": recorded_at}
            for sha in added
        ),
    ]
    key = document.entry_key(str(entry["branch"]), str(entry["target"]))
    entries[key] = entry
    if added:
        upsert_json_section(
            conn,
            item_id=int(item_id),
            section=document.MERGE_RECEIPTS_SECTION,
            payload={document.ENTRIES_KEY: entries},
            ordering=document.MERGE_RECEIPTS_ORDERING,
        )
    return {
        "branch": entry["branch"],
        "target": entry["target"],
        "attested": added,
        "already_recorded": [sha for sha in shas if sha in already],
    }


__all__ = ["CommitAttestationRefused", "attest_commits"]
