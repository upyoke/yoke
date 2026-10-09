"""Record a promoted project's delivered identity without inventing output."""

from __future__ import annotations

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    parse_bound_sources,
)
from yoke_core.domain.hosted_promotion_receipt import (
    PROMOTION_RECEIPTS_KEY,
    PromotionReceiptRefused,
    validate_promotion_receipt,
)
from yoke_core.domain.json_helper import dumps_compact


def verify_promotion_provenance(project, receipt):
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.project_github_auth import resolve_project_github_auth
    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.github_actions_receipt import read_run_receipt
    from yoke_core.domain.hosted_promotion_receipt import PROMOTION_ARTIFACT_PREFIX

    auth = resolve_project_github_auth(
        project, required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS
    )
    if auth.repo != receipt["repository"]:
        raise PromotionReceiptRefused(
            "promotion_repository_mismatch",
            "project binding differs from receipt repository",
        )
    run = rest_get(
        f"/repos/{auth.repo}/actions/runs/{receipt['run_id']}/attempts/{receipt['run_attempt']}",
        token=auth.token,
    )
    if (
        not isinstance(run, dict)
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise PromotionReceiptRefused(
            "promotion_run_not_successful", "exact promotion attempt did not succeed"
        )
    verified = read_run_receipt(
        auth.repo, run, PROMOTION_ARTIFACT_PREFIX, token=auth.token
    )
    if verified != receipt:
        raise PromotionReceiptRefused(
            "promotion_receipt_provenance_mismatch",
            "supplied proof differs from the immutable GitHub artifact",
        )


def record_promotion_receipt(conn, *, run_id, project, commit_sha, receipt, reason):
    from yoke_core.domain.deployment_run_release_output_record import (
        OUTCOME_ALREADY_RECORDED,
        OUTCOME_NOTHING_PRODUCED,
        ReleaseOutputRefused,
        _p,
        _run_record,
        record_release_output,
    )
    from yoke_core.domain.deployment_run_project_sources import (
        recorded_source_sha,
        invalidate_run_source_facts,
    )
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
        open_carried_work_source,
    )
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.github_actions_receipt import ActionsReceiptRefused
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.project_github_auth import ProjectGithubAuthError

    project_id = int(resolve_project_id(conn, project))
    run = _run_record(conn, run_id)
    environment = conn.execute(
        f"SELECT e.name FROM deployment_runs dr JOIN environments e "
        f"ON e.id=dr.target_environment_id WHERE dr.id={_p(conn)}",
        (run_id,),
    ).fetchone()
    try:
        payload = validate_promotion_receipt(
            receipt,
            environment=str(environment[0]) if environment else "",
            product_sha=run["release_lineage"],
            commit_sha=commit_sha,
        )
        verify_promotion_provenance(project, receipt)
    except PromotionReceiptRefused as exc:
        raise ReleaseOutputRefused(exc.reason, str(exc)) from exc
    except (ActionsReceiptRefused, RestTransportError, ProjectGithubAuthError) as exc:
        raise ReleaseOutputRefused(
            "promotion_receipt_unverifiable",
            f"promotion provenance could not be verified ({getattr(exc, 'reason', getattr(exc, 'code', 'github_read_failed'))}); "
            "restore project GitHub Actions read capability or receipt availability and re-record; do not redeploy",
        ) from exc
    if not commit_sha:
        raise ReleaseOutputRefused(
            "promotion_commit_required",
            "name --commit with the exact receipt SHA, then record again",
        )
    pinned = recorded_source_sha(run, project_id)
    if not pinned or project_id == run["project_id"]:
        raise ReleaseOutputRefused(
            "promotion_source_unbound",
            "promotion must name a project this run bound; repair the run source binding before recording",
        )
    try:
        source = open_carried_work_source(conn, project_id)
    except CarriedWorkSourceUnavailable as exc:
        raise ReleaseOutputRefused(exc.reason, f"{exc.reason}; {exc.recovery}") from exc
    sha = payload["platform_sha"]
    proven = payload["proven_consumer_sha"]
    if (
        source.resolve_commit(sha) != sha
        or source.contains_commit(sha, pinned) is not True
    ):
        raise ReleaseOutputRefused(
            "promotion_candidate_ancestry_unproven",
            "deployed SHA must verifiably contain the exact bound candidate; repair source access or select the correct promotion receipt",
        )
    if (
        source.resolve_commit(proven) != proven
        or source.contains_commit(proven, pinned) is not True
        or source.contains_commit(sha, proven) is not True
    ):
        raise ReleaseOutputRefused(
            "promotion_consumer_ancestry_unproven",
            "actual proven consumer must contain the bound candidate and be contained in the deployed SHA; select the correct proof receipt",
        )
    outcome = {
        "run_id": run_id,
        "project": project,
        "project_id": project_id,
        "commit_sha": sha,
        "reason": reason,
        "recorded": False,
        "outcome": OUTCOME_NOTHING_PRODUCED,
    }
    initial_sources = parse_bound_sources(run[BOUND_SOURCES_FIELD])
    initial_entry = next(
        e for e in initial_sources["projects"] if e.get("project_id") == project_id
    )
    prior = initial_entry.get(PROMOTION_RECEIPTS_KEY, [])
    if any(
        r["payload"]["run_id"] == payload["run_id"]
        and r["payload"]["run_attempt"] > payload["run_attempt"]
        for r in prior
    ):
        raise ReleaseOutputRefused(
            "promotion_attempt_stale",
            "a newer promotion attempt is already recorded; recover the latest immutable attempt receipt",
        )
    if payload["pin_pushed"]:
        outcome = record_release_output(
            conn,
            run_id=run_id,
            project=project,
            commit_sha=sha,
            reason=reason,
        )
    # The generic writer above may have appended output. Keep it and all
    # prior attempt provenance when recording the deployed identity.
    run = _run_record(conn, run_id)
    stored = run[BOUND_SOURCES_FIELD]
    sources = parse_bound_sources(stored)
    entry = next(e for e in sources["projects"] if e.get("project_id") == project_id)
    receipts = entry.setdefault(PROMOTION_RECEIPTS_KEY, [])
    identity = (payload["run_id"], payload["run_attempt"])
    previous = next(
        (
            r
            for r in receipts
            if (r["payload"]["run_id"], r["payload"]["run_attempt"]) == identity
        ),
        None,
    )
    if previous is not None:
        if previous != receipt:
            raise ReleaseOutputRefused(
                "promotion_receipt_changed",
                "immutable promotion attempt already holds different proof; retain both records and repair the mismatched receipt",
            )
        return {**outcome, "outcome": OUTCOME_ALREADY_RECORDED}
    receipts.append(receipt)
    updated = conn.execute(
        f"UPDATE deployment_runs SET {BOUND_SOURCES_FIELD}={_p(conn)} "
        f"WHERE id={_p(conn)} AND COALESCE({BOUND_SOURCES_FIELD},'')={_p(conn)}",
        (dumps_compact(sources), run_id, stored),
    )
    if updated.rowcount == 0:
        raise ReleaseOutputRefused(
            "sources_changed_during_record",
            "run sources changed while recording; re-read the exact receipt and retry",
        )
    invalidate_run_source_facts(conn, run_id)
    return {**outcome, "recorded": True}
