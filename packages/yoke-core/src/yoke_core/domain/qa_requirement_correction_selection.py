"""Resolve an exact failed obligation before correction cases fan out."""

from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key
from yoke_core.domain.qa_requirement_replacement import QaReplacementError, _row
from yoke_core.domain.qa_requirement_supersession import same_scope


def resolve_correction_selection(conn, declarations):
    resolved, scopes = [], {}
    seen = set()
    for value in declarations:
        entry = dict(value)
        failed_id = int(entry["requirement_id"])
        if failed_id in seen:
            raise QaReplacementError(
                f"requirement {failed_id} is declared twice; name each failed requirement once"
            )
        seen.add(failed_id)
        failed = _row(conn, failed_id)
        if failed is None:
            raise QaReplacementError(
                f"requirement {failed_id} not found; inspect the failed requirement"
            )
        if entry.get("case_key") is None:
            if not failed.get("plan_case_key"):
                raise QaReplacementError(
                    f"requirement {failed_id} has no plan case key; inspect the failed "
                    "requirement and use --replaces CASE_KEY=REQUIREMENT_ID instead."
                )
            key = base_case_key(failed["plan_case_key"])
            entry.update(case_key=key, exact_scope=True)
        scopes.setdefault(entry["case_key"], []).append(failed)
        resolved.append(entry)
    return resolved, scopes


def validate_item_correction_selection(
    conn, *, item_id, transition_id, attachments, scopes, requirement_ids
):
    """Distinguish an absent snapshot from a wrong key or obligation scope.

    The materializer supplies its effective attachments and resulting rows;
    ordinary gate materialization never reads current cases for this check.
    """
    from shlex import quote

    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.project_identity import render_item_ref, resolve_project_slug
    from yoke_core.domain.qa_plan_case_definition import (
        case_baselines, materialized_definition, plan_cases,
    )
    from yoke_core.domain.qa_plan_case_targets import case_variants
    from yoke_core.domain.qa_plan_management import _plan_row

    rows = [_row(conn, rid) for rid in requirement_ids]
    for key, failed_rows in scopes.items():
        for failed in failed_rows:
            if (
                failed.get("deployment_run_id")
                or failed.get("item_id") != item_id
                or failed.get("workflow_transition_id") != transition_id
            ):
                raise QaReplacementError(
                    "replacement_scope_mismatch: the failed requirement "
                    f"{failed['id']} is outside this item transition. "
                    "Use its own item and transition (or deployment run and stage)."
                )
        if any(row and row["plan_case_key"] == key for row in rows):
            continue  # Existing-row ambiguity and scope validation own this case.
        candidates = []
        for plan_id, attachment in attachments.items():
            plan = _plan_row(conn, plan_id)
            cases = [case for case in plan_cases(conn, plan_id) if case["case_key"] == key]
            for case, env, target in case_variants(conn, plan=plan, cases=cases):
                for position, baseline in enumerate(case_baselines(case), start=1):
                    candidates.append({
                        "item_id": item_id,
                        **materialized_definition(
                            plan=plan, case=case, qa_phase=attachment["qa_phase"],
                            baseline=baseline, baseline_position=position,
                            transition_id=transition_id, execution_target=target,
                            target_env=env,
                        ),
                    })
        if not candidates:
            raise QaReplacementError(
                f"replacement_case_unknown: corrected key {key!r} is absent from "
                "this item transition's applicable current plans and snapshot. "
                "Inspect the attached plans and correct --replaces; refresh cannot add an unknown key."
            )
        for failed in failed_rows:
            matches = [row for row in candidates if not same_scope(failed, row)]
            if not matches:
                raise QaReplacementError(
                    f"replacement_scope_mismatch: corrected key {key!r} cannot answer "
                    f"requirement {failed['id']}'s obligation. Keep its item, transition, "
                    "phase, target and host baseline when correcting the plan."
                )
            if len(matches) != 1:
                raise QaReplacementError(
                    f"replacement_case_ambiguous: corrected key {key!r} matches "
                    f"{len(matches)} current cases for requirement {failed['id']}. "
                    "Name one unambiguous corrected key in --replaces."
                )
            item = query_one(conn, "SELECT project_id FROM items WHERE id=%s", (item_id,))
            subject = (
                f"--item {quote(render_item_ref(conn, item_id))} "
                f"--transition {quote(transition_id)} "
                f"--project {quote(resolve_project_slug(conn, int(item['project_id'])))}"
            )
            declaration = quote(f"{key}={failed['id']}")
            raise QaReplacementError(
                f"replacement_materialization_stale: corrected key {key!r} is in "
                "the applicable current plan but absent from this item's stable snapshot. "
                "Retain the failed case and add a distinct corrected key, then run "
                f"`yoke qa plan rematerialize {subject}` followed by "
                f"`yoke qa plan materialize {subject} --replaces {declaration}`. "
                "Refresh updates matching rows, adds eligible cases and retires removed "
                "cases; a removed post-deploy case may already gain an automatic successor."
            )
