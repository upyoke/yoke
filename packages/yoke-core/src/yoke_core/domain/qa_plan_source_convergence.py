"""Bring source-bound QA plans to the cases the serving build authors.

Item attachment and a release run's start freeze a plan's cases as they stand.
A release usually freezes before its own build boots, so boot convergence
alone would leave that release on the old cases; before a stage first
materializes the plan, :mod:`deployment_qa_source_plan_refresh` takes the
cases converged here when the run's candidate carries their source. Only plans
already bound to a source commit move, and
only forward: :func:`replace_plan_cases` proves the build is merged and
descends from the plan's recorded source, so an older build never rewrites a
plan a newer one converged.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.db_helpers import query_rows

_log = logging.getLogger(__name__)

_REGRESSION = "qa_plan_source_revision_regression"


def converge_source_bound_plans(conn: Any, build_sha: str | None = None) -> list[dict]:
    """Replace each drifted source-bound plan's cases with this build's.

    Returns one outcome per examined plan. A plan that cannot converge keeps
    its cases and is logged with its reason and recovery; it never fails boot.
    A server without a baked build commit (a source checkout) has no source
    revision to record, so it converges nothing.
    """
    revision = (
        build_sha if build_sha is not None else os.environ.get("YOKE_BUILD_SHA", "")
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return []
    from yoke_core.domain.qa_plan_detail import get_plan
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.tools.installer_campaign_plan import (
        SOURCE_AUTHORED_PLAN_SLUGS,
        compare_plan,
    )

    slugs = ",".join(["%s"] * len(SOURCE_AUTHORED_PLAN_SLUGS))
    rows = query_rows(
        conn,
        "SELECT id, slug, source_revision FROM qa_plans "
        "WHERE source_revision IS NOT NULL AND source_revision<>%s "
        f"AND retired_at IS NULL AND slug IN ({slugs}) ORDER BY id",
        (revision, *SOURCE_AUTHORED_PLAN_SLUGS),
    )
    outcomes = []
    for row in rows:
        plan_id = int(row["id"])
        outcome = {"plan_id": plan_id, "slug": str(row["slug"])}
        try:
            cases, report = compare_plan(get_plan(conn, plan_id=plan_id))
            if report["matches_source"]:
                outcome["result"] = "current"
            else:
                replace_plan_cases(
                    conn, plan_id=plan_id, cases=cases, source_revision=revision
                )
                outcome["result"] = "converged"
                outcome["differences"] = report["differences"]
                _log.info(
                    "qa_plan_source_converged: plan %s (%s) now holds the cases "
                    "of build %s: %s",
                    plan_id,
                    row["slug"],
                    revision,
                    report["differences"],
                )
        except Exception as exc:  # noqa: BLE001 - boot availability wins
            conn.rollback()
            outcome["result"] = "skipped"
            outcome["reason"] = f"{type(exc).__name__}: {exc}"
            if str(exc).startswith(_REGRESSION):
                _log.info(
                    "qa_plan_source_newer_kept: plan %s (%s) keeps source %s; "
                    "build %s is older and leaves it unchanged.",
                    plan_id,
                    row["slug"],
                    row["source_revision"],
                    revision,
                )
            else:
                _log.warning(
                    compose_refusal(
                        (
                            "qa_plan_source_convergence_failed: plan %s (%s) kept its cases from "
                            "source %s, so item QA will materialize those, not build %s. Reason: %s."
                        ),
                        recovery=(
                            "fix the reason and restart the server, or export and sync the cases by "
                            "hand with yoke qa plan-cases sync "
                            "(docs/testing-verification/installer-campaign.md)."
                        ),
                    ),
                    plan_id,
                    row["slug"],
                    row["source_revision"],
                    revision,
                    outcome["reason"],
                )
        outcomes.append(outcome)
    return outcomes


__all__ = ["converge_source_bound_plans"]
