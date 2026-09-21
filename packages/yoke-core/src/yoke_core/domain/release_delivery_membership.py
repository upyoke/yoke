"""Recorded answers for whether a release already delivered a merge.

Membership in a succeeded run is delivery. An item whose recorded merge is
newer than that run cannot have been in it. Honest ``carried_work`` may still
name a commit; a payload that could not look, or that warns its checkout was
not refreshed, must not. Ancestry is only the residual: merged before the
candidate, never a member, not honestly carried.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.release_delivery_attestation import (
    has_attestation_changing_warning,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _carrier(run: dict[str, Any]) -> dict[str, str]:
    return {
        "run_id": str(run.get("id") or ""),
        "flow": str(run.get("flow") or ""),
    }


def _contents_known(payload: dict[str, Any]) -> bool:
    derivation = payload.get("derivation")
    return isinstance(derivation, dict) and bool(derivation.get("contents_known"))


def _honest(payload: dict[str, Any]) -> bool:
    return _contents_known(payload) and not has_attestation_changing_warning(payload)


def honest_carried_shas(
    raw: Any,
    *,
    bound_project_id: int | None = None,
) -> set[str]:
    """Commits one run named, only when that record says it actually looked."""
    payload = loads_text(str(raw or "{}"))
    if not isinstance(payload, dict):
        return set()
    slice_payload = payload
    if bound_project_id is not None:
        slice_payload = next(
            (
                entry
                for entry in payload.get("bound_projects") or []
                if isinstance(entry, dict)
                and entry.get("project_id") == bound_project_id
            ),
            {},
        )
        if not isinstance(slice_payload, dict):
            return set()
    if not (_honest(slice_payload) or _honest(payload)):
        return set()
    carried: set[str] = set()
    for entry in slice_payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        for sha in entry.get("commit_shas") or []:
            text = str(sha or "").strip()
            if text:
                carried.add(text)
    return carried


def carriage_by_sha(runs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Each honestly carried commit, against the newest release that named it."""
    carried: dict[str, dict[str, str]] = {}
    for run in runs:
        carrier = _carrier(run)
        for sha in honest_carried_shas(
            run.get("carried_work"),
            bound_project_id=run.get("bound_project_id"),
        ):
            carried.setdefault(sha, carrier)
    return carried


def newest_lineage_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The newest release with a pinned lineage, or an empty mapping."""
    return next(
        (run for run in runs if str(run.get("release_lineage") or "").strip()),
        {},
    )


def succeeded_run_members(
    conn: Any,
    runs: list[dict[str, Any]],
) -> dict[int, dict[str, str]]:
    """Each item enrolled on these succeeded runs, newest run first."""
    run_by_id = {
        str(run.get("id") or ""): run
        for run in runs
        if str(run.get("id") or "").strip()
    }
    if not run_by_id or not _table_exists(conn, "deployment_run_items"):
        return {}
    marker = _placeholder(conn)
    placeholders = ", ".join(marker for _ in run_by_id)
    rows = query_rows(
        conn,
        "SELECT item_id, run_id FROM deployment_run_items "
        f"WHERE run_id IN ({placeholders})",
        tuple(run_by_id),
    )
    by_run: dict[str, list[int]] = {}
    for row in rows:
        by_run.setdefault(str(row["run_id"] or ""), []).append(int(row["item_id"]))
    members: dict[int, dict[str, str]] = {}
    for run in runs:
        for item_id in by_run.get(str(run.get("id") or ""), ()):
            members.setdefault(item_id, _carrier(run))
    return members


class ReleaseDeliveryIndex:
    """One release line's recorded answers, with ancestry as the last resort."""

    def __init__(
        self,
        conn: Any,
        *,
        project_id: int,
        runs: list[dict[str, Any]],
        containment_cls: Callable[..., Any],
    ) -> None:
        self._conn = conn
        self._project_id = int(project_id)
        self._containment_cls = containment_cls
        self._members = succeeded_run_members(conn, runs)
        self._carriage = carriage_by_sha(runs)
        newest = newest_lineage_run(runs)
        self._newest_lineage = str(newest.get("release_lineage") or "").strip()
        self._newest_completed = str(newest.get("completed_at") or "").strip()
        self._newest_carrier = (
            _carrier(newest)
            if self._newest_lineage
            else {
                "run_id": "",
                "flow": "",
            }
        )
        self._containment: Any = None
        self._merged_at: dict[int, str] = {}

    def carrier_for(
        self,
        sha: str,
        *,
        item_id: int | None = None,
    ) -> dict[str, str] | None:
        """The release that delivered ``sha``, or ``None`` if none has.

        Membership and recency are facts of the item. Honest carried work and
        ancestry are facts of the commit. Asked in that order, so a member
        never spends a subprocess, and a merge that landed after the newest
        succeeded candidate never asks whether that candidate contains it.
        """
        commit = str(sha or "").strip()
        if item_id is not None:
            member = self._members.get(int(item_id))
            if member is not None:
                return dict(member)
            if self._merge_is_newer(int(item_id)):
                return None
        if not commit:
            return None
        carried = self._carriage.get(commit)
        if carried is not None:
            return dict(carried)
        return self._ancestry(commit)

    def _merge_is_newer(self, item_id: int) -> bool:
        """Whether this item's recorded merge is after the newest candidate."""
        if not self._newest_completed:
            return False
        merged_at = self._item_merged_at(item_id)
        return bool(merged_at) and merged_at > self._newest_completed

    def _item_merged_at(self, item_id: int) -> str:
        if item_id in self._merged_at:
            return self._merged_at[item_id]
        stamp = ""
        if _table_exists(self._conn, "items") and _column_exists(
            self._conn,
            "items",
            "merged_at",
        ):
            marker = _placeholder(self._conn)
            rows = query_rows(
                self._conn,
                f"SELECT merged_at FROM items WHERE id={marker}",
                (item_id,),
            )
            if rows:
                stamp = str(rows[0].get("merged_at") or "").strip()
        self._merged_at[item_id] = stamp
        return stamp

    def _ancestry(self, sha: str) -> dict[str, str] | None:
        if not self._newest_lineage:
            return None
        if self._containment is None:
            self._containment = self._containment_cls(
                self._conn,
                self._project_id,
                candidate_lineage=self._newest_lineage,
            )
        if self._containment.contains(sha).contained:
            return dict(self._newest_carrier)
        return None


__all__ = [
    "ReleaseDeliveryIndex",
    "carriage_by_sha",
    "honest_carried_shas",
    "newest_lineage_run",
    "succeeded_run_members",
]
