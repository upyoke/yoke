"""Attest candidate containment once, then serve cards from its snapshot.

The serving control plane owns the candidate and merge identities, but an
HTTPS server has no project checkout from which to compare them. It therefore
builds a digest-bound question set, the local deployment driver answers that
set from registered checkouts, and the server validates and stores the answer
at the created-to-executing boundary. An unreadable graph refuses the start;
it never becomes a confident empty snapshot.
"""

from __future__ import annotations

from yoke_core.domain.deployment_run_recovery_command import deploy_command
from typing import Any, Callable, Mapping

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_run_containment_basis import (
    CANDIDATE_CONTAINMENT_FIELD,
    CANDIDATE_CONTAINMENT_SCHEMA,
    _basis_digest,
    candidate_containment_basis,
)
from yoke_core.domain.domain_refusal import DomainRefusal
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists


class CandidateContainmentRefusal(DomainRefusal, ValueError):
    """The start cannot safely record its immutable containment snapshot."""

    def __init__(self, code: str, detail: str, recovery: str) -> None:
        self.code = code
        self.recovery = recovery
        super().__init__(compose_refusal(f"{code}: {detail};", recovery=f"{recovery}"))


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
                f"candidate and merge commits, then re-drive the run with `{deploy_command()}`.",
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
                    f"project {slug or project_id} item {item.get('public_ref') or render_item_ref(None, item_id)}: {verdict.reason}",
                    verdict.recovery
                    or "Fetch both commits into the registered checkout, then "
                    f"re-drive the run with `{deploy_command()}`.",
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
            f"Read a fresh execution context and re-drive {run_id} with `yoke watch deploy -- {run_id}`.",
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
            f"Read a fresh execution context and re-drive {run_id} with `yoke watch deploy -- {run_id}`.",
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
    if _column_exists(conn, "deployment_runs", CANDIDATE_CONTAINMENT_FIELD):
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
