"""Read a carried member's obligations before deployment cases are created."""

from yoke_core.domain.deployment_overview_timing import overview_phase

from collections import defaultdict

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_member_qa_sources import (
    current_sources,
    decoded,
    definitions,
    identity,
    stage_environments,
)
from yoke_core.domain.qa_activity_reads import _list_activity
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.deployment_qa_run_sharing import (
    member_shared_plan_ids,
    run_qa_sharing,
)


def _copy_matches(conn, row, member, run, *, historical):
    """A same-title or former-target result cannot answer this release.

    A shared copy has no owner and is drawn once under Run QA, never inside
    any one member's section.
    """
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )

    owner = row.get("deployment_member_item_id")
    if owner is None or int(owner) != member:
        return False
    if historical:
        return True
    subject = deployment_qa_stage_subject(
        conn,
        run_id=str(run["id"]),
        stage_name=row["deployment_stage"],
        member_item_id=member,
        require_active=False,
    )
    target = deployment_qa_execution_target(conn, subject)
    return row.get("execution_target_digest") == target_digest(target)


@presentation_operation
def _member_qa_obligations(conn, runs, members):
    """Bound all reads to authorized carried members and displayed releases."""
    item_ids = {int(m["id"]) for values in members.values() for m in values}
    if not item_ids:
        return {}
    run_ids = tuple(str(run["id"]) for run in runs)
    markers = ",".join("%s" for _ in run_ids)
    from yoke_core.domain.deployment_qa_presentation_facts import run_member_rows

    snapshots = {
        (run_id, member): row["requirement_snapshot"]
        for run_id in run_ids
        if members.get(run_id)
        for member, row in run_member_rows(conn, run_id).items()
        if member in item_ids
    }
    active_ids = sorted(
        {
            int(m["id"])
            for run in runs
            if str(run.get("status")) not in {"succeeded", "failed", "cancelled"}
            for m in members.get(str(run["id"]), [])
        }
    )
    sources, plans = current_sources(conn, active_ids)
    sharing = run_qa_sharing(conn, run_ids)
    environments = _environments(conn, members)
    copies = query_rows(
        conn,
        "SELECT q.id,q.deployment_run_id,q.deployment_stage,q.deployment_member_item_id,"
        "q.plan_id,q.plan_case_key,q.host_baseline,q.target_env,q.execution_target_json,"
        "q.execution_target_digest,q.waived_at,q.retracted_at,q.superseded_by_requirement_id,"
        "q.replacement_requirement_id,q.method_id,q.method_config,q.instructions,"
        "q.expected_outcome FROM qa_requirements q "
        f"WHERE q.deployment_run_id IN ({markers}) "
        "AND q.qa_phase='post_deploy' AND q.qa_kind<>'deployment_stage_acceptance' "
        "ORDER BY q.id DESC",
        run_ids,
    )
    by_run = defaultdict(list)
    for row in copies:
        by_run[str(row["deployment_run_id"])].append(dict(row))
    identities = {}

    def copy_identity(row):
        copy_id = int(row["id"])
        if copy_id not in identities:
            identities[copy_id] = identity(row)
        return identities[copy_id]

    result, evidence_ids = {}, set()
    for run in runs:
        run_id = str(run["id"])
        names, dynamic, target_error = stage_environments(conn, run.get("stages"), run)
        historical = str(run.get("status")) in {"succeeded", "failed", "cancelled"}
        for member in members.get(run_id, []):
            key = (run_id, int(member["id"]))
            try:
                snapshot = decoded(snapshots.get(key), {}) if historical else {}
                selected = definitions(
                    snapshot.get("requirements", []) if historical else sources[key[1]],
                    snapshot.get("plans", []) if historical else plans[key[1]],
                    environments=environments,
                    environment_names=names,
                    dynamic=dynamic,
                )
                shared = member_shared_plan_ids(sharing, run_id, key[1])
                current, history, used = [], [], set()
                for definition_key, definition in selected.items():
                    if definition.get("plan_id") in shared:
                        continue
                    candidates = [
                        row
                        for row in by_run[run_id]
                        if copy_identity(row) == definition_key
                        and _copy_matches(conn, row, key[1], run, historical=historical)
                    ]
                    live = [
                        row
                        for row in candidates
                        if not _withdrawn(row)
                        and (historical or _same_content(row, definition))
                    ]
                    chosen = live[0] if live else None
                    if chosen is not None and not definition.get("waived_at"):
                        current.append({"requirement_id": int(chosen["id"])})
                        used.add(int(chosen["id"]))
                        evidence_ids.add(int(chosen["id"]))
                    elif not candidates or any(
                        not _withdrawn(row) for row in candidates
                    ):
                        current.append(_pending(definition, run_id, member))
                    for row in candidates:
                        if int(row["id"]) not in used:
                            history.append({"requirement_id": int(row["id"])})
                            evidence_ids.add(int(row["id"]))
                # Run-native cases have no intake source. Their own immutable
                # requirement remains authoritative, including older releases
                # whose admission snapshot did not enumerate those cases.
                from yoke_core.domain.deployment_qa_admission_materialization import (
                    admitted_source_requirement_id,
                )

                for row in by_run[run_id]:
                    row_id = int(row["id"])
                    if (
                        copy_identity(row) in selected
                        or row.get("deployment_member_item_id") != key[1]
                    ):
                        continue
                    if not historical and (
                        row.get("plan_id") is not None
                        or admitted_source_requirement_id(row.get("plan_case_key"))
                        is not None
                    ):
                        continue
                    if not _copy_matches(conn, row, key[1], run, historical=historical):
                        continue
                    field = (
                        history
                        if _withdrawn(row) or row.get("replacement_requirement_id")
                        else current
                    )
                    field.append({"requirement_id": row_id})
                    evidence_ids.add(row_id)
                result[key] = {"current": current, "history": history}
                if target_error:
                    result[key]["error"] = target_error
            except (LookupError, ValueError) as exc:
                result[key] = {
                    "current": [],
                    "history": [],
                    "error": f"item_qa_requirements_unreadable: {exc}. Reload this run; "
                    "if it persists, ask the project operator to repair the named QA definition or target.",
                }
    evidence, _ = (
        _list_activity(
            conn,
            identity=None,
            requirement_ids=sorted(evidence_ids),
            limit=max(1, len(evidence_ids)),
        )
        if evidence_ids
        else ([], None)
    )
    by_id = {int(row["requirement_id"]): row for row in evidence}
    for (run_id, member_id), projection in result.items():
        for field in ("current", "history"):
            projection[field] = [
                by_id.get(int(row["requirement_id"]), row)
                if row.get("requirement_id") is not None
                else row
                for row in projection[field]
            ]
    return result


def _withdrawn(row):
    """Retracted and superseded checks leave every count; history keeps them."""
    return bool(row.get("retracted_at") or row.get("superseded_by_requirement_id"))


def member_snapshot_rows(conn, run_ids):
    """One frozen snapshot set for obligations and acceptance of these runs."""
    markers = ",".join("%s" for _ in run_ids)
    rows = query_rows(
        conn,
        "SELECT dri.run_id,dri.item_id,dri.requirement_snapshot,i.project_id,dr.status "
        "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
        "JOIN deployment_runs dr ON dr.id=dri.run_id "
        f"WHERE dri.run_id IN ({markers})",
        run_ids,
    )
    by_run = defaultdict(dict)
    for row in rows:
        by_run[str(row["run_id"])][int(row["item_id"])] = row
    return by_run


def _environments(conn, members):
    projects = sorted(
        {int(m["project_id"]) for values in members.values() for m in values}
    )
    return {
        int(row["id"]): str(row["name"])
        for row in query_rows(
            conn,
            "SELECT e.id,e.name FROM environments e JOIN sites s ON s.id=e.site "
            f"WHERE s.project_id IN ({','.join('%s' for _ in projects)})",
            tuple(projects),
        )
    }


def _pending(definition, run_id, member):
    source_id = definition.get("source_requirement_id")
    return {
        **definition,
        "requirement_id": source_id,
        "source_requirement_id": source_id,
        "deployment_run_id": run_id,
        "run_id": None,
        "outcome": "queued",
        "execution_status": "queued",
        "artifacts": [],
        "evidence_count": 0,
        "project": member["project_id"],
        "verdict_reason": None,
        "pending_obligation": True,
    }


@overview_phase("qa_obligations")
def member_qa_obligations(conn, runs, members):
    from yoke_core.domain.deployment_qa_presentation_facts import member_presentation

    @member_presentation
    def read_scoped(connection, subjects):
        return _member_qa_obligations(connection, runs, members)

    try:
        return read_scoped(
            conn,
            [
                (str(run["id"]), int(member["id"]), str(run.get("current_stage") or ""))
                for run in runs
                for member in members.get(str(run["id"]), [])
            ],
        )
    except Exception as exc:
        # Keep the authorized run visible when its auxiliary read fails. Never
        # turn a failed requirement read into a claim that no QA was selected.
        return {
            (str(run["id"]), int(member["id"])): {
                "current": [],
                "history": [],
                "error": f"item_qa_requirements_read_failed ({type(exc).__name__}): Reload this run. "
                "If it persists, ask the project operator to inspect the carried-item QA read.",
            }
            for run in runs
            for member in members.get(str(run["id"]), [])
        }


def _same_content(copy, definition):
    from yoke_core.domain.qa_deployment_case_content_refresh import case_content_digest

    return case_content_digest(copy) == case_content_digest(definition)
