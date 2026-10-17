"""Bind reusable source-authored QA cases to the commits they describe."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, query_scalar
from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
    SOURCE_CHECKOUT,
    open_carried_work_source,
)
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder
from yoke_core.domain.schema_common import _column_exists

SOURCE_BINDING_UNAVAILABLE = (
    "qa_plan_source_binding_unavailable: source-bound QA plans require the "
    "serving release carrying qa.plan_cases.sync, qa_plans.source_revision and boot convergence; "
    "ask the control-plane operator to serve that release before syncing."
)


def require_merged_source(conn: Any, project_id: int, revision: str) -> Any:
    """Verify exact source ancestry on this project's declared default branch.

    Returns the opened source so callers can ask further ancestry questions.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
        raise QaPlanError(
            "qa_plan_source_revision_invalid: supply the full source commit SHA"
        )
    value = query_scalar(
        conn, "SELECT default_branch FROM projects WHERE id=%s", (project_id,)
    )
    branch = str(value or "")
    try:
        if not branch:
            raise ValueError("the project has no declared default branch")
        source = open_carried_work_source(conn, project_id)
        if source.origin == SOURCE_CHECKOUT:
            from yoke_cli.config.repo_upstream_freshness import refresh_base_branch

            reading = refresh_base_branch(source.location, branch, use_cache=False)
            if not reading.verified:
                raise ValueError(reading.note)
            tip = reading.upstream_sha or source.resolve_commit(branch)
        else:
            tip = source.resolve_commit(branch)
        if not tip or source.contains_commit(tip, revision) is not True:
            raise ValueError(f"source commit {revision} is not proven on {branch}")
    except (
        CarriedWorkSourceUnavailable,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        raise QaPlanError(
            f"qa_plan_source_unmerged_or_unverified: {exc}; sync after merge "
            "from verified source, or use item-scoped/run-bound correction cases."
        ) from exc
    return source


def require_forward_source(source: Any, recorded: str, revision: str) -> None:
    """A source-bound plan only moves to its recorded revision or a descendant.

    An older revision would silently revert definitions a later sync landed.
    """
    if revision == recorded:
        return
    recovery = (
        "No cases were written. Export the cases from current main or another "
        f"descendant of {recorded}, then sync again."
    )
    try:
        if source.resolve_commit(recorded) != recorded:
            raise ValueError(
                f"the plan's recorded source {recorded} is not in the project "
                "repository"
            )
        carried = source.contains_commit(revision, recorded)
        if carried is None:
            raise ValueError("the project source cannot answer ancestry")
    except (
        CarriedWorkSourceUnavailable,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        raise QaPlanError(
            f"qa_plan_source_ancestry_unverified: {exc}, so source {revision} "
            f"cannot be proven to descend from {recorded}. {recovery} Restore "
            "project repository read access if it is unavailable."
        ) from exc
    if carried is not True:
        raise QaPlanError(
            f"qa_plan_source_revision_regression: source {revision} does not "
            f"descend from the plan's recorded source {recorded}; syncing it "
            f"would revert newer case definitions. {recovery}"
        )


def update_plan_source(
    conn: Any, plan: Mapping[str, Any], revision: str | None, now: Any
) -> None:
    """Update the durable source binding on the case writer's transaction."""
    marker = _placeholder(conn)
    supported = _column_exists(conn, "qa_plans", "source_revision")
    if revision is not None and not supported:
        raise QaPlanError(SOURCE_BINDING_UNAVAILABLE)
    column = "source_revision" if supported else "NULL AS source_revision"
    lock = " FOR UPDATE" if marker == "%s" else ""
    current_revision = query_scalar(
        conn,
        f"SELECT {column} FROM qa_plans WHERE id={marker}{lock}",
        (int(plan["id"]),),
    )
    if current_revision and revision is None:
        raise QaPlanError(
            "qa_plan_source_revision_required: this plan is source-bound; "
            "use qa plan-cases sync with a clean, merged source export."
        )
    values = [instant_parameter(conn, now)]
    assignment = f"updated_at={marker}"
    if revision is not None:
        source = require_merged_source(conn, int(plan["project_id"]), revision)
        if current_revision:
            require_forward_source(source, str(current_revision), revision)
        assignment += f",source_revision={marker}"
        values.append(revision)
    conn.execute(
        f"UPDATE qa_plans SET {assignment} WHERE id={marker}",
        (*values, int(plan["id"])),
    )


def require_candidate_plan(conn: Any, plan: Mapping[str, Any], run_id: str) -> None:
    """A run may materialize only source definitions its own candidate carries."""
    revision = plan.get("source_revision")
    if not revision:
        if _column_exists(conn, "qa_plans", "source_revision"):
            from yoke_core.domain.deployment_qa_presentation_reads import (
                presentation_read,
            )
            from yoke_core.domain.deployment_qa_shared_plan_reads import (
                presented_plan_rows,
            )

            batch = presented_plan_rows(conn, int(plan["id"]))

            current = presentation_read(
                conn,
                ("qa_current_plan_source", int(plan["id"])),
                lambda: (
                    batch[0].get("source_revision")
                    if batch is not None
                    else query_scalar(
                        conn,
                        "SELECT source_revision FROM qa_plans WHERE id=%s",
                        (int(plan["id"]),),
                    )
                ),
            )
            if current:
                raise QaPlanError(
                    "qa_plan_source_snapshot_missing: this frozen plan predates source "
                    "binding; retain its evidence and select a source-proven plan for "
                    "the candidate, or use a run-bound correction."
                )
        return
    project_id = int(plan["project_id"])
    try:
        candidate = run_delivered_sha(conn, run_id, project_id)
        if not candidate or not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
            raise ValueError("candidate or saved-plan source revision is unavailable")
        source = open_carried_work_source(conn, project_id)
        candidate = source.resolve_commit(candidate)
        if (
            not candidate
            or source.contains_commit(candidate, str(revision)) is not True
        ):
            raise ValueError(
                f"candidate {candidate or 'unavailable'} does not carry source {revision}"
            )
    except (
        CarriedWorkSourceUnavailable,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        raise QaPlanError(
            f"qa_plan_source_candidate_mismatch: plan {plan['id']} for run {run_id}: "
            f"{exc}; no cases were materialized. Release a candidate carrying the "
            "plan source, or keep corrections scoped to this run; a saved plan "
            "never syncs back to an older source."
            " Restore project repository read access if ancestry is unavailable."
        ) from exc
