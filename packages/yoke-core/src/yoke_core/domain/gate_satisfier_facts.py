"""The extended capability registry a satisfier ladder resolves against.

Four kinds of fact answer "what can this project prove?", and the key
prefix names which kind a fact is, so provenance travels with the fact
instead of being reconstructed by readers:

``declared:``
    Operator-authored truth already in the control plane — a
    ``project_capabilities`` row, or a project scalar such as the
    default branch. A declared capability is an obligation, not a hint:
    declaring CI means CI gets enforced, and the sanctioned way back
    down is undeclaring it.

``derived:``
    Truth nobody declared but the control plane can observe about
    itself, converged into ``project_derived_facts`` on every
    ``project.snapshot.sync``, and observed live when a project has not
    converged one yet. See
    :mod:`yoke_core.domain.project_derived_facts`.

``item:``
    Truth about one item that the control plane holds — whether a
    passing CI run is recorded, whether an item-bound deployment run
    succeeded. See :mod:`yoke_core.domain.gate_satisfier_item_facts`.

``observed:``
    Truth only the gate site can see, probed during this one call —
    whether a ref resolves in this worktree, whether the merge this
    transition attempted actually ran.

A fact is PRESENT, ABSENT, or UNKNOWN, and the three stay distinct all
the way to the refusal text. UNKNOWN is the one that used to become a
silent pass: an unanswerable question is not the same as a negative
answer, and the ladder says which it hit rather than guessing. It is
reserved for what genuinely cannot be answered — an unreadable catalog,
or a fact no source in this registry owns — so it never stands in for
"nobody has run a sync yet".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


class FactVerdict(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# Declared facts: capability rows are keyed by their capability type.
def capability_fact(capability_type: str) -> str:
    return f"declared:capability:{capability_type}"


DECLARED_DEFAULT_BRANCH = "declared:default_branch"

DERIVED_REMOTE_PRESENT = "derived:remote_present"
DERIVED_TEST_COMMAND_DECLARED = "derived:test_command_declared"
DERIVED_ENVIRONMENTS_PRESENT = "derived:environments_present"
DERIVED_DEFAULT_BRANCH = "derived:default_branch"

OBSERVED_GIT_REPOSITORY = "observed:git_repository"
OBSERVED_REMOTE_INTEGRATION_REF = "observed:remote_integration_ref"
OBSERVED_LOCAL_INTEGRATION_REF = "observed:local_integration_ref"
OBSERVED_MERGE_RECORDED = "observed:merge_recorded"
OBSERVED_NO_IMPLEMENTATION_BRANCH = "observed:no_implementation_branch"

_UNKNOWN_RECOVERY = {
    "derived": (
        "no converged observation for this fact; run "
        "`yoke project snapshot sync` to converge the project's derived "
        "facts, then retry"
    ),
    "declared": (
        "the control plane holds no declaration for this fact; declare it "
        "on the project before the rung it gates can run"
    ),
    "item": (
        "the control plane holds no record answering this fact for this "
        "item; produce the evidence the rung names, or take the rung "
        "below it"
    ),
    "observed": (
        "the gate site did not probe this fact on this call; this is an "
        "engine defect — the consumer must pass every fact its ladder "
        "names"
    ),
}


@dataclass(frozen=True)
class Fact:
    key: str
    verdict: FactVerdict
    value: str = ""
    detail: str = ""


@dataclass
class CapabilityFacts:
    """A resolved fact registry for one project at one moment."""

    facts: Dict[str, Fact] = field(default_factory=dict)

    def with_observed(
        self, observed: Mapping[str, Tuple[bool, str]],
    ) -> "CapabilityFacts":
        """Return a copy carrying this call's site-probed facts.

        ``observed`` maps a fact key to ``(present, detail)``. Callers
        probe once and pass the result, so the ladder never reaches back
        into git or the filesystem itself.
        """
        merged = dict(self.facts)
        for key, (present, detail) in observed.items():
            merged[key] = Fact(
                key=key,
                verdict=FactVerdict.PRESENT if present else FactVerdict.ABSENT,
                value="",
                detail=detail,
            )
        return CapabilityFacts(facts=merged)

    def verdict(self, key: str) -> FactVerdict:
        fact = self.facts.get(key)
        return fact.verdict if fact else FactVerdict.UNKNOWN

    def value(self, key: str) -> str:
        fact = self.facts.get(key)
        return fact.value if fact else ""

    def present(self, key: str) -> bool:
        return self.verdict(key) is FactVerdict.PRESENT

    def explain(self, key: str) -> str:
        fact = self.facts.get(key)
        if fact is not None and fact.detail:
            return fact.detail
        if fact is not None:
            return f"recorded as {fact.verdict.value}"
        prefix = key.split(":", 1)[0]
        return _UNKNOWN_RECOVERY.get(
            prefix, "no source in this registry answers this fact"
        )

    def snapshot(self) -> Dict[str, str]:
        """Return a flat ``key -> verdict`` map for durable stamping."""
        return {
            key: fact.verdict.value for key, fact in sorted(self.facts.items())
        }


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def load_project_facts(
    conn: Any,
    project_id: int,
    *,
    item_id: Optional[int] = None,
    observed: Optional[Mapping[str, Tuple[bool, str]]] = None,
) -> CapabilityFacts:
    """Compose the fact registry a ladder resolves against.

    Declared capability rows and the project's declared default branch
    are read directly; derived facts come from the converged
    ``project_derived_facts`` rows; passing ``item_id`` folds in that
    item's control-plane observations. Site-probed facts are layered on
    top via ``observed``.
    """
    facts: Dict[str, Fact] = {}
    for capability_type in _declared_capability_types(conn, project_id):
        facts[capability_fact(capability_type)] = Fact(
            key=capability_fact(capability_type),
            verdict=FactVerdict.PRESENT,
            value=capability_type,
            detail=(
                f"project declares the {capability_type!r} capability"
            ),
        )
    declared_branch = _declared_default_branch(conn, project_id)
    if declared_branch is not None:
        facts[DECLARED_DEFAULT_BRANCH] = Fact(
            key=DECLARED_DEFAULT_BRANCH,
            verdict=(
                FactVerdict.PRESENT if declared_branch else FactVerdict.ABSENT
            ),
            value=declared_branch,
            detail=(
                f"projects.default_branch is {declared_branch!r}"
                if declared_branch
                else "projects.default_branch is blank"
            ),
        )
    facts.update(_derived_facts(conn, project_id))
    if item_id is not None:
        from yoke_core.domain.gate_satisfier_item_facts import load_item_facts

        facts.update(load_item_facts(conn, item_id))
    registry = CapabilityFacts(facts=facts)
    if observed:
        registry = registry.with_observed(observed)
    return registry


def _declared_capability_types(conn: Any, project_id: int) -> list[str]:
    # Probe the catalog rather than letting a missing table raise: on
    # Postgres a failed statement aborts the whole transaction, so a
    # swallowed error would silently turn every LATER fact unknown too.
    if not _table_exists(conn, "project_capabilities"):
        return []
    p = _p(conn)
    rows = conn.execute(
        f"SELECT type FROM project_capabilities WHERE project_id = {p} "
        "ORDER BY type",
        (project_id,),
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _declared_default_branch(conn: Any, project_id: int) -> Optional[str]:
    if not _table_exists(conn, "projects"):
        return None
    p = _p(conn)
    row = conn.execute(
        f"SELECT default_branch FROM projects WHERE id = {p}",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0] or "").strip()


def _derived_facts(conn: Any, project_id: int) -> Dict[str, Fact]:
    """Read the converged derived facts, observing live where none exist.

    Convergence at snapshot sync is the normal source. A project that
    has not synced since these facts existed has no rows, and reading
    that as unknown would refuse correct work for a reason the operator
    did nothing to cause — so each missing fact is observed on the spot
    from the same control-plane reads the convergence uses, and the
    stored rows stay a warm cache rather than a precondition.
    """
    from yoke_core.domain.project_derived_facts import DERIVED_FACT_KEYS, observe_now

    out: Dict[str, Fact] = {}
    if _table_exists(conn, "project_derived_facts"):
        p = _p(conn)
        rows = conn.execute(
            "SELECT fact_key, present, fact_value, observed_from "
            f"FROM project_derived_facts WHERE project_id = {p}",
            (project_id,),
        ).fetchall()
        for row in rows:
            key = f"derived:{row[0]}"
            present = bool(int(row[1] or 0))
            out[key] = Fact(
                key=key,
                verdict=FactVerdict.PRESENT if present else FactVerdict.ABSENT,
                value=str(row[2] or ""),
                detail=str(row[3] or "converged at project snapshot sync"),
            )
    for fact_key in DERIVED_FACT_KEYS:
        key = f"derived:{fact_key}"
        if key in out:
            continue
        observation = observe_now(conn, project_id, fact_key)
        if observation is None:
            continue
        present, value, observed_from = observation
        out[key] = Fact(
            key=key,
            verdict=FactVerdict.PRESENT if present else FactVerdict.ABSENT,
            value=value,
            detail=f"{observed_from} (observed live; not yet converged)",
        )
    return out


__all__ = [
    "CapabilityFacts",
    "DECLARED_DEFAULT_BRANCH",
    "DERIVED_DEFAULT_BRANCH",
    "DERIVED_ENVIRONMENTS_PRESENT",
    "DERIVED_REMOTE_PRESENT",
    "DERIVED_TEST_COMMAND_DECLARED",
    "Fact",
    "FactVerdict",
    "OBSERVED_GIT_REPOSITORY",
    "OBSERVED_LOCAL_INTEGRATION_REF",
    "OBSERVED_MERGE_RECORDED",
    "OBSERVED_NO_IMPLEMENTATION_BRANCH",
    "OBSERVED_REMOTE_INTEGRATION_REF",
    "capability_fact",
    "load_project_facts",
]
