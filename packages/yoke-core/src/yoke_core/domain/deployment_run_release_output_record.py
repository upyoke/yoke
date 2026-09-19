"""The guarded write that records a commit a release's own automation produced.

Recording is guarded rather than trusted, because a record that could absorb
any commit would be a waiver wearing an attribution's clothes. Four claims
have to hold before one is written: the run has started and so has a source
record to extend, the ref resolves in the project's source, the commit is not
the one the run pinned and does descend from it, and no backlog item already
owns it. Each refusal names itself and the repair.

The shape being written, and the reading side attribution consults, are
:mod:`yoke_core.domain.deployment_run_release_output`.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_sources_recorded,
    declared_bindings,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_release_output import (
    REASON_RELEASE_PIN,
    RELEASE_OUTPUT_KEY,
)
from yoke_core.domain.json_helper import dumps_compact


#: What one recording call settled, for a caller that must tell the three
#: apart: a new record, a repeat of one already held, and a release whose
#: promotion added no commit to that project at all.
OUTCOME_RECORDED = "recorded"
OUTCOME_ALREADY_RECORDED = "already_recorded"
OUTCOME_NOTHING_PRODUCED = "no_commit_produced"


class ReleaseOutputRefused(ValueError):
    """The commit cannot be recorded as this run's release output."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _attributed_item(conn: Any, source: Any, project_id: int, sha: str) -> str:
    """The item ref already claiming ``sha``, or ``""`` when none does.

    Asked of the same resolver carried-work derivation uses, over a range of
    exactly this one commit, so the guard and the consumer can never disagree
    about who owns it. The range runs from the commit's own parent rather
    than from itself: a range whose base equals its head contains the commit
    by name but excludes it from every ancestry question, which would blind
    the lane-commit pass to the one commit being asked about.
    """
    from yoke_core.domain.deployment_run_carried_work_sources import (
        resolve_carried_items,
    )

    known_items, resolved, _warnings = resolve_carried_items(
        conn,
        project_id=int(project_id),
        source=source,
        base=str(source.resolve_commit(f"{sha}^") or sha),
        head=sha,
        commits=(sha,),
    )
    for item_id in sorted(resolved.get(sha, set())):
        return known_items.get(int(item_id), str(item_id))
    return ""


def _run_record(conn: Any, run_id: str) -> dict[str, Any]:
    """The run's stored source record, its own project, and its flow stages."""
    row = conn.execute(
        f"SELECT dr.project_id,COALESCE(dr.release_lineage,'') AS release_lineage,"
        f"COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD},"
        "COALESCE(df.stages,'[]') AS stages FROM deployment_runs dr "
        f"LEFT JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    return {
        "project_id": int(_cell(row, "project_id", 0)),
        "release_lineage": str(_cell(row, "release_lineage", 1) or ""),
        BOUND_SOURCES_FIELD: str(_cell(row, BOUND_SOURCES_FIELD, 2) or ""),
        "stages": str(_cell(row, "stages", 3) or "[]"),
    }


def _bound_branch(stages_json: str, project: str) -> str:
    """The branch this run's own flow bound for ``project``, or ``""``.

    Read from the flow rather than passed in, so no caller has to name a
    repository branch that the control plane already recorded.
    """
    import json

    try:
        stages = json.loads(stages_json or "[]")
    except (TypeError, ValueError):
        return ""
    try:
        declared = declared_bindings(stages if isinstance(stages, list) else [])
    except ValueError:
        return ""
    for binding in declared.values():
        if binding.get("project") == project:
            return str(binding.get("branch") or "")
    return ""


def _merged_record(
    stored: Mapping[str, Any],
    *,
    project: str,
    project_id: int,
    sha: str,
    reason: str,
) -> tuple[dict[str, Any], bool]:
    """Add one produced commit to the project's entry, creating it if absent."""
    payload = dict(stored)
    projects = [dict(entry) for entry in payload.get("projects") or []]
    target = next(
        (
            entry
            for entry in projects
            if entry.get("project_id") is not None
            and int(entry["project_id"]) == int(project_id)
        ),
        None,
    )
    if target is None:
        # A run producing a commit in a project it never bound — its own, most
        # often — still has somewhere to say so. The entry carries no
        # ``commit_sha``, and every bound-source reader skips an entry without
        # one, so recording output can never invent a pinned source.
        target = {"project": project, "project_id": int(project_id)}
        projects.append(target)
    outputs = [dict(output) for output in target.get(RELEASE_OUTPUT_KEY) or []]
    if any(str(output.get("commit_sha") or "").lower() == sha for output in outputs):
        return payload, False
    outputs.append({"commit_sha": sha, "reason": reason})
    target[RELEASE_OUTPUT_KEY] = outputs
    payload["projects"] = sorted(
        projects, key=lambda entry: str(entry.get("project") or "")
    )
    return payload, True


def record_release_output(
    conn: Any,
    *,
    run_id: str,
    project: str,
    commit_sha: str = "",
    reason: str = REASON_RELEASE_PIN,
) -> dict[str, Any]:
    """Record that ``run_id``'s own automation produced a commit.

    ``commit_sha`` takes any ref the project's source resolves, and an empty
    one resolves the branch this run's own flow bound for that project — so a
    caller never has to name a repository branch the control plane already
    recorded.

    Refuses rather than records whenever the claim cannot be proved: an
    unstarted run has no source record to extend, an unreadable ref is not a
    commit, the commit the run pinned is not one it produced, a commit that
    does not descend from that pinned source belongs to another run, and a
    commit a backlog item already owns is that item's work however the caller
    labelled it.
    """
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
        open_carried_work_source,
    )
    from yoke_core.domain.deployment_run_project_sources import (
        recorded_source_sha,
    )
    from yoke_core.domain.project_identity import resolve_project_id

    if not bound_sources_recorded(conn):
        raise ReleaseOutputRefused(
            "bound_sources_unconverged",
            "this control plane has not converged deployment_runs.bound_sources, "
            "which is where a run records the commits it produced; deploy the "
            "build carrying that column, then record again",
        )
    project_id = int(resolve_project_id(conn, project))
    run = _run_record(conn, run_id)
    stored_text = str(run[BOUND_SOURCES_FIELD])
    if not stored_text:
        raise ReleaseOutputRefused(
            "run_sources_unresolved",
            f"deployment run {run_id!r} has not resolved its source bindings "
            "yet, so it cannot yet say what it produced; record after the run "
            "has started",
        )
    named = str(commit_sha or "").strip()
    ref = named or _bound_branch(run["stages"], project)
    if not ref:
        raise ReleaseOutputRefused(
            "produced_commit_unnamed",
            f"deployment run {run_id!r} binds no branch of project {project!r}, "
            "so the commit it produced cannot be resolved from the flow; name "
            "the commit explicitly",
        )
    try:
        source = open_carried_work_source(conn, project_id)
    except CarriedWorkSourceUnavailable as exc:
        raise ReleaseOutputRefused(
            exc.reason,
            f"project {project!r} commits cannot be read here: {exc.reason}; "
            f"{exc.recovery}",
        ) from exc
    sha = str(source.resolve_commit(ref) or "").strip().lower()
    if not sha:
        raise ReleaseOutputRefused(
            "commit_unresolvable",
            f"{ref!r} does not resolve in project {project!r}; push the "
            "commit, or name one this project's source can read",
        )
    pinned = recorded_source_sha(
        {
            "project_id": run["project_id"],
            "release_lineage": run["release_lineage"],
            BOUND_SOURCES_FIELD: stored_text,
        },
        project_id,
    ).strip().lower()
    if pinned and sha == pinned:
        # The branch still points where this run pinned it, so the release
        # added no commit to that project. That is an ordinary outcome for a
        # promotion whose materialization was already current, and the receipt
        # says so rather than inventing a record. A caller that named the
        # commit itself asserted otherwise, and is wrong out loud.
        if named:
            raise ReleaseOutputRefused(
                "commit_is_pinned_source",
                f"commit {sha[:12]} is the source deployment run {run_id!r} "
                f"pinned for project {project!r}, not one it produced; name "
                "the commit the run's automation pushed, or omit --commit to "
                "resolve the bound branch",
            )
        return {
            "run_id": run_id,
            "project": project,
            "project_id": project_id,
            "commit_sha": "",
            "reason": str(reason or REASON_RELEASE_PIN),
            "recorded": False,
            "outcome": OUTCOME_NOTHING_PRODUCED,
        }
    # A commit this release wrote descends from the commit it pinned. One that
    # does not is somebody else's — an earlier release's output, or work on
    # another line — and crediting it here would move the attribution off the
    # run that actually owns it. A source that cannot answer ancestry says so
    # by returning no answer, and the item guard below still applies.
    if pinned and source.contains_commit(sha, pinned) is False:
        raise ReleaseOutputRefused(
            "commit_precedes_pinned_source",
            f"commit {sha[:12]} does not descend from {pinned[:12]}, the "
            f"source deployment run {run_id!r} pinned for project {project!r}, "
            "so that run did not produce it; record it against the run that did",
        )
    owner = _attributed_item(conn, source, project_id, sha)
    if owner:
        raise ReleaseOutputRefused(
            "commit_attributed_to_item",
            f"commit {sha[:12]} already resolves to {owner}, so it is that "
            "item's work and not release output; recording it would waive the "
            "delivery proof that item owes. Record only a commit a release's "
            "own automation wrote",
        )
    payload, changed = _merged_record(
        parse_bound_sources(stored_text),
        project=project,
        project_id=project_id,
        sha=sha,
        reason=str(reason or REASON_RELEASE_PIN),
    )
    if changed:
        marker = _p(conn)
        updated = conn.execute(
            f"UPDATE deployment_runs SET {BOUND_SOURCES_FIELD}={marker} "
            f"WHERE id={marker} AND COALESCE({BOUND_SOURCES_FIELD},'')={marker}",
            (dumps_compact(payload), run_id, stored_text),
        )
        if getattr(updated, "rowcount", 1) == 0:
            raise ReleaseOutputRefused(
                "sources_changed_during_record",
                f"deployment run {run_id!r} recorded different source commits "
                "while this record was resolving; re-read the run and record "
                "again",
            )
    return {
        "run_id": run_id,
        "project": project,
        "project_id": project_id,
        "commit_sha": sha,
        "reason": str(reason or REASON_RELEASE_PIN),
        "recorded": changed,
        "outcome": OUTCOME_RECORDED if changed else OUTCOME_ALREADY_RECORDED,
    }


__all__ = [
    "OUTCOME_ALREADY_RECORDED",
    "OUTCOME_NOTHING_PRODUCED",
    "OUTCOME_RECORDED",
    "ReleaseOutputRefused",
    "record_release_output",
]
