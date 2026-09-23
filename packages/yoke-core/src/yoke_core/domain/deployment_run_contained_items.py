"""Attest candidate containment once, then serve cards from its snapshot.

The serving control plane owns the candidate and merge identities, but an
HTTPS server has no project checkout from which to compare them. It therefore
builds a digest-bound question set, the local deployment driver answers that
set from registered checkouts, and the server validates and stores the answer
at the created-to-executing boundary. An unreadable graph refuses the start;
it never becomes a confident empty snapshot.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.delivery_landing_custody import merged_open_items
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.item_finished_times import finished_times_in_window
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.schema_common import _column_exists


CANDIDATE_CONTAINMENT_FIELD = "candidate_containment"
CANDIDATE_CONTAINMENT_SCHEMA = 1


class CandidateContainmentRefusal(ValueError):
    """The start cannot safely record its immutable containment snapshot."""

    def __init__(self, code: str, detail: str, recovery: str) -> None:
        self.code = code
        self.recovery = recovery
        super().__init__(f"{code}: {detail}; Recovery: {recovery}")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def parse_candidate_containment(value: Any) -> dict[str, Any]:
    """Return the stored snapshot, or an explicit not-recorded result."""
    empty = {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "derivation": {
            "status": "not_recorded",
            "contents_known": False,
            "reason": "candidate_containment_not_recorded",
        },
        "items": [],
    }
    if value in (None, ""):
        return empty
    payload = dict(value) if isinstance(value, Mapping) else None
    if payload is None:
        try:
            parsed = loads_text(str(value))
        except (TypeError, ValueError):
            return empty
        payload = dict(parsed) if isinstance(parsed, Mapping) else None
    if payload is None:
        return empty
    payload.setdefault("schema", CANDIDATE_CONTAINMENT_SCHEMA)
    payload.setdefault("derivation", empty["derivation"])
    payload.setdefault("items", [])
    return payload


def _carried_project_ids(run: Mapping[str, Any]) -> tuple[int, ...]:
    project_id = int(run["project_id"])
    payload = parse_bound_sources(run.get(BOUND_SOURCES_FIELD))
    bound = [pid for pid in bound_project_shas(payload) if pid != project_id]
    return (project_id, *sorted(bound))


def _visibility_item_ids(conn: Any, project_id: int) -> tuple[int, ...]:
    """Items a live delivery box could name: open, or finished today."""
    found = {int(record["id"]) for record in merged_open_items(conn, project_id)}
    finished = finished_times_in_window(conn)
    if finished:
        ids = sorted(finished)
        marker = _p(conn)
        holes = ", ".join(marker for _ in ids)
        rows = query_rows(
            conn,
            f"SELECT id FROM items WHERE project_id={marker} AND id IN ({holes})",
            (int(project_id), *ids),
        )
        found.update(int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows)
    return tuple(sorted(found))


def _basis_digest(basis: Mapping[str, Any]) -> str:
    payload = {
        "schema": int(basis.get("schema") or CANDIDATE_CONTAINMENT_SCHEMA),
        "primary_project": str(basis.get("primary_project") or ""),
        "projects": list(basis.get("projects") or ()),
    }
    return sha256(dumps_compact(payload).encode("utf-8")).hexdigest()


def candidate_containment_basis(conn: Any, run_id: str) -> dict[str, Any]:
    """Return the server-owned questions a local checkout must answer."""
    if not _column_exists(conn, "deployment_runs", CANDIDATE_CONTAINMENT_FIELD):
        raise CandidateContainmentRefusal(
            "candidate_containment_schema_unconverged",
            "deployment_runs.candidate_containment is missing",
            "Boot the current build to converge its additive schema, then re-drive "
            f"{run_id}.",
        )
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id,release_lineage,bound_sources,"
        f"{CANDIDATE_CONTAINMENT_FIELD} FROM deployment_runs WHERE id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    stored = _cell(row, CANDIDATE_CONTAINMENT_FIELD, 3)
    if stored not in (None, ""):
        return {
            "schema": CANDIDATE_CONTAINMENT_SCHEMA,
            "recorded_snapshot": parse_candidate_containment(stored),
        }
    run = {
        "project_id": int(_cell(row, "project_id", 0)),
        "release_lineage": _cell(row, "release_lineage", 1),
        "bound_sources": _cell(row, "bound_sources", 2),
    }
    project_ids = _carried_project_ids(run)
    holes = ", ".join(marker for _ in project_ids)
    slug_rows = query_rows(
        conn,
        f"SELECT id,slug FROM projects WHERE id IN ({holes})",
        tuple(project_ids),
    )
    slugs = {int(row["id"]): str(row["slug"]) for row in slug_rows}
    projects: list[dict[str, Any]] = []
    for project_id in project_ids:
        item_ids = _visibility_item_ids(conn, project_id)
        merges = recorded_merge_shas_for_items(conn, item_ids)
        items = [
            {"id": item_id, "merge_sha": merges[item_id][0]}
            for item_id in item_ids
            if merges.get(item_id)
        ]
        projects.append(
            {
                "project_id": project_id,
                "project": slugs.get(project_id, ""),
                "candidate_lineage": recorded_source_sha(run, project_id),
                "items": items,
            }
        )
    basis = {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "primary_project": slugs.get(project_ids[0], ""),
        "projects": projects,
    }
    basis["basis_digest"] = _basis_digest(basis)
    return basis


def attest_candidate_containment(
    basis: Mapping[str, Any], checkout_for_project: Callable[[str], str]
) -> dict[str, Any]:
    """Answer a server basis from local checkouts or refuse it by name."""
    recorded = basis.get("recorded_snapshot")
    if isinstance(recorded, Mapping):
        return dict(recorded)
    answers: list[dict[str, Any]] = []
    contained: list[dict[str, int]] = []
    for project in basis.get("projects") or ():
        project_id = int(project["project_id"])
        slug = str(project.get("project") or "")
        project_items = list(project.get("items") or ())
        if not project_items:
            continue
        checkout = str(checkout_for_project(slug) or "")
        if not checkout:
            raise CandidateContainmentRefusal(
                "candidate_containment_checkout_missing",
                f"no local checkout is registered for project {slug or project_id}",
                "Register that project's checkout on the deploy driver, fetch the "
                "candidate and merge commits, then re-drive the run.",
            )
        walk = CandidateContainment(
            None,
            project_id,
            candidate_lineage=str(project.get("candidate_lineage") or ""),
            source=LocalCheckoutSource(checkout),
        )
        for item in project_items:
            item_id = int(item["id"])
            merge_sha = str(item.get("merge_sha") or "")
            verdict = walk.contains(merge_sha)
            if verdict.state == UNDETERMINED:
                raise CandidateContainmentRefusal(
                    "candidate_containment_undetermined",
                    f"project {slug or project_id} item {item_id}: {verdict.reason}",
                    verdict.recovery
                    or "Fetch both commits into the registered checkout, then "
                    "re-drive the run.",
                )
            answer = {
                "id": item_id,
                "project_id": project_id,
                "candidate_lineage": str(project.get("candidate_lineage") or ""),
                "merge_sha": merge_sha,
                "state": verdict.state,
                "source": verdict.source,
            }
            answers.append(answer)
            if verdict.state == CONTAINED:
                contained.append({"id": item_id, "project_id": project_id})
    return {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "basis_digest": str(basis.get("basis_digest") or ""),
        "derivation": {
            "status": "known",
            "contents_known": True,
            "source": "attested_local_checkout",
        },
        "answers": answers,
        "items": sorted(contained, key=lambda item: item["id"]),
    }


def record_attested_candidate_containment(
    conn: Any, run_id: str, attestation: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Validate a local answer against current DB facts and persist it once."""
    basis = candidate_containment_basis(conn, run_id)
    recorded = basis.get("recorded_snapshot")
    if isinstance(recorded, Mapping):
        return dict(recorded)
    expected = {
        (
            int(project["project_id"]),
            int(item["id"]),
            str(project.get("candidate_lineage") or ""),
            str(item.get("merge_sha") or ""),
        )
        for project in basis["projects"]
        for item in project.get("items") or ()
    }
    if not expected and attestation is None:
        attestation = attest_candidate_containment(basis, lambda _slug: "")
    if not isinstance(attestation, Mapping):
        raise CandidateContainmentRefusal(
            "candidate_containment_attestation_required",
            "the server cannot derive candidate containment without a checkout",
            f"Start {run_id} through the local deployment driver so it can attest "
            "the server-provided containment basis.",
        )
    if str(attestation.get("basis_digest") or "") != _basis_digest(basis):
        raise CandidateContainmentRefusal(
            "candidate_containment_attestation_stale",
            "the attestation does not match the run's current candidate basis",
            f"Read a fresh execution context and re-drive {run_id}.",
        )
    answers = list(attestation.get("answers") or ())
    actual = {
        (
            int(answer["project_id"]),
            int(answer["id"]),
            str(answer.get("candidate_lineage") or ""),
            str(answer.get("merge_sha") or ""),
        )
        for answer in answers
    }
    states = {str(answer.get("state") or "") for answer in answers}
    if (
        len(answers) != len(expected)
        or actual != expected
        or not states.issubset({CONTAINED, NOT_CONTAINED})
    ):
        raise CandidateContainmentRefusal(
            "candidate_containment_attestation_invalid",
            "the attestation does not answer every current containment question",
            f"Read a fresh execution context and re-drive {run_id}.",
        )
    snapshot = {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "basis_digest": _basis_digest(basis),
        "derivation": {
            "status": "known",
            "contents_known": True,
            "source": "attested_local_checkout",
        },
        "answers": answers,
        "items": sorted(
            [
                {"id": int(answer["id"]), "project_id": int(answer["project_id"])}
                for answer in answers
                if answer.get("state") == CONTAINED
            ],
            key=lambda item: item["id"],
        ),
    }
    marker = _p(conn)
    conn.execute(
        f"UPDATE deployment_runs SET {CANDIDATE_CONTAINMENT_FIELD}={marker} "
        f"WHERE id={marker}",
        (dumps_compact(snapshot), run_id),
    )
    return snapshot


__all__ = [
    "CANDIDATE_CONTAINMENT_FIELD",
    "CandidateContainmentRefusal",
    "attest_candidate_containment",
    "candidate_containment_basis",
    "parse_candidate_containment",
    "record_attested_candidate_containment",
]
