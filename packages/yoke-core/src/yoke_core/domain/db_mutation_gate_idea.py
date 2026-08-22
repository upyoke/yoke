"""Idea → refining-idea joint gate.

Owns :func:`check_idea_to_refining_idea_gate` — the joint validator that
proves *intent* before refining-idea: profile schema, opportunistic
mechanical scanner, attestation presence, model + flow cross-reference,
and cross-item overlap.

This gate does not require migration module files to exist on disk —
refine proves intent; implementation proves artifacts;
:func:`check_implementing_to_reviewing_implementation_gate` proves
apply-audit evidence.  The scanner inspects module DDL opportunistically
when the file already exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.db_compatibility_attestation import AUTHORED_FIELDS
from yoke_core.domain.db_mutation_compat_scanner import (
    UnsupportedDbKindError,
    scan as scan_ddl,
)
from yoke_core.domain.db_mutation_gate_evidence import (
    _extract_candidate_ddl,
    _read_module_text,
    _resolve_module_path,
)
from yoke_core.domain.db_mutation_gate_loaders import (
    ItemIdRefMismatch,
    _load_capability_settings,
    _load_item_row,
    _other_non_terminal_profiles,
    _resolve_repo_path,
)
from yoke_core.domain.db_mutation_gate_overlap import detect_overlap
from yoke_core.domain.db_mutation_gate_shared import (
    GateOutcome,
    _now_iso,
    _safe_parse_dict,
)
from yoke_core.domain.db_mutation_gate_strategy import evaluate_strategy_matrix
from yoke_core.domain.db_mutation_profile import (
    COMPATIBILITY_PRE_MERGE_SAFE,
    MUTATION_INTENT_APPLY,
    STATE_NONE,
    DbMutationProfileError,
    validate as validate_profile,
)
from yoke_core.domain.db_mutation_gate_dependency_pairs import (
    load_dependency_pairs,
)
from yoke_core.domain.migration_model_capability import resolve_model
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.projects_breakage_policy import (
    BreakagePolicyError,
    resolve_breakage_policy,
)


def check_idea_to_refining_idea_gate(
    item_id: int,
    *,
    conn: Optional[Any] = None,
) -> GateOutcome:
    """Joint gate proving migration intent before refining-idea.

    Profiles with ``state="none"`` pass trivially.  When ``state="declared"``
    the gate runs (a) profile schema, (b) opportunistic mechanical scanner,
    (c) attestation presence (when ``pre_merge_safe``), (d) model + flow
    cross-reference, (e) cross-item overlap.  On pass the caller stamps
    ``frozen_at`` via :func:`stamp_attestation_frozen_at`.

    This gate proves *intent*, not artifacts: declared migration module
    slugs do **not** need to resolve to files on disk here.  The file is
    authored during implementation, enforced at rehearsal time by the
    runner, and apply-audit evidence is enforced at
    :func:`check_implementing_to_reviewing_implementation_gate`.  The
    mechanical scanner reads DDL opportunistically when the module file
    already exists. Missing files stay outside this intent gate; a missing
    machine-local checkout is recorded as a non-blocking warning.
    """

    def _evaluate(c: Any) -> GateOutcome:
        try:
            item = _load_item_row(c, item_id)
        except ItemIdRefMismatch as exc:
            return GateOutcome(passed=False, errors=[str(exc)])
        if item is None:
            return GateOutcome(
                passed=False,
                errors=[f"Item {render_item_ref(c, item_id)} not found"],
            )

        raw_profile = item.get("db_mutation_profile")
        parsed_profile = _safe_parse_dict(raw_profile)
        # Step (a): structural validation.
        if not parsed_profile:
            return GateOutcome(
                passed=False,
                errors=[
                    f"{render_item_ref(c, item_id)} db_mutation_profile is "
                    "empty/null; every item must carry the negative default "
                    '{"state":"none"}'
                ],
            )
        try:
            profile = validate_profile(parsed_profile)
        except DbMutationProfileError as exc:
            return GateOutcome(
                passed=False,
                errors=[f"db_mutation_profile invalid: {exc}"],
            )

        if profile["state"] == STATE_NONE:
            return GateOutcome(passed=True)

        errors: List[str] = []
        warnings: List[str] = []
        escalations: List[Dict[str, Any]] = []
        attestation = _safe_parse_dict(item.get("db_compatibility_attestation"))
        compatibility_class = profile.get("compatibility_class")

        # Step (c): attestation presence when pre_merge_safe.
        if compatibility_class == COMPATIBILITY_PRE_MERGE_SAFE:
            missing = []
            for fname in sorted(AUTHORED_FIELDS):
                value = attestation.get(fname)
                if value is None:
                    missing.append(fname)
                    continue
                if isinstance(value, str) and not value.strip():
                    missing.append(fname)
                elif isinstance(value, (list, tuple, dict)) and len(value) == 0:
                    missing.append(fname)
            if missing:
                errors.append(
                    "db_compatibility_attestation must carry non-empty "
                    f"authored fields when compatibility_class=pre_merge_safe; "
                    f"missing/empty: {sorted(missing)}.  This auto-downgrades "
                    f"the class to pre_merge_breaking — fix the attestation "
                    f"or change compatibility_class."
                )
                escalations.append(
                    {
                        "from": COMPATIBILITY_PRE_MERGE_SAFE,
                        "to": "pre_merge_breaking",
                        "reason": (
                            "missing/empty authored attestation fields: "
                            f"{sorted(missing)}"
                        ),
                        "source": "joint_gate",
                        "observed_at": _now_iso(),
                    }
                )

        # Step (d): model + flow cross-reference.
        project = item.get("project") or ""
        if not project:
            errors.append(
                f"{render_item_ref(c, item_id)} has no project — cannot "
                "resolve migration_model capability or deployment flow"
            )
            return GateOutcome(passed=False, errors=errors, escalations=escalations)

        capability_settings = _load_capability_settings(c, project)
        if capability_settings is None:
            errors.append(
                f"project '{project}' has no valid migration_model capability; "
                "work items on projects without a declared model must use "
                'db_mutation_profile.state = "none"'
            )
            return GateOutcome(passed=False, errors=errors, escalations=escalations)

        model_name = profile["model_name"]
        try:
            model = resolve_model(capability_settings, model_name)
        except KeyError:
            available = sorted((capability_settings.get("models") or {}).keys())
            errors.append(
                f"db_mutation_profile.model_name '{model_name}' is not "
                f"declared in project '{project}' migration_model capability "
                f"(available: {available})"
            )
            return GateOutcome(passed=False, errors=errors, escalations=escalations)

        runner = model.get("runner") or {}
        runner_kind = runner.get("kind")

        # Model configuration check (DB-sourced runner kind + config).
        # File existence for declared migration_modules is intentionally
        # NOT checked here — see docstring: refine proves intent,
        # implementation proves artifacts.
        repo_path = _resolve_repo_path(c, project)
        if runner_kind == "governed_migration_module":
            modules_dir = (runner.get("config") or {}).get("modules_dir")
            if not modules_dir:
                errors.append(
                    f"runner.config.modules_dir missing on model "
                    f"'{model_name}' for project '{project}'"
                )
        elif runner_kind == "external_adapter":
            errors.append(
                "external_adapter runners are reserved in governed DB-mutation gate — combination "
                "not yet supported"
            )

        if (
            profile["mutation_intent"] == MUTATION_INTENT_APPLY
            and runner_kind == "governed_migration_module"
            and repo_path is None
        ):
            warnings.append(
                f"mechanical DDL scan skipped: project '{project}' has no "
                "machine-local checkout on this execution host"
            )

        # Step (b): mechanical scanner — runs after module-file resolution
        # so we can read the actual DDL.
        if (
            profile["mutation_intent"] == MUTATION_INTENT_APPLY
            and runner_kind == "governed_migration_module"
            and repo_path is not None
        ):
            modules_dir = (runner.get("config") or {}).get("modules_dir") or ""
            authoritative_kind = (model.get("authoritative_db") or {}).get("kind")
            if authoritative_kind:
                for identifier in profile["migration_modules"]:
                    mod_path = _resolve_module_path(repo_path, modules_dir, identifier)
                    text = _read_module_text(mod_path)
                    if text is None:
                        continue
                    ddl_text = _extract_candidate_ddl(text)
                    try:
                        hits = scan_ddl(
                            ddl_text,
                            authoritative_db_kind=authoritative_kind,
                        )
                    except UnsupportedDbKindError:
                        continue
                    if hits and compatibility_class == COMPATIBILITY_PRE_MERGE_SAFE:
                        for hit in hits:
                            errors.append(
                                f"scanner banned-pattern hit in migration "
                                f"module '{identifier}' "
                                f"(line {hit.line_number}): "
                                f"{hit.pattern_id} — {hit.reason}"
                            )
                            escalations.append(
                                {
                                    "from": COMPATIBILITY_PRE_MERGE_SAFE,
                                    "to": "pre_merge_breaking",
                                    "reason": (
                                        f"scanner pattern {hit.pattern_id} in "
                                        f"{identifier}:{hit.line_number} — "
                                        f"{hit.snippet}"
                                    ),
                                    "source": "scanner",
                                    "observed_at": _now_iso(),
                                }
                            )

        # Step (e): cross-item overlap.  Dependency-aware bypass treats
        # candidate ↔ other pairs that already carry a blocks/depends-on
        # edge in ``item_dependencies`` as serializable, so overlapping
        # destructive declarations on shared surfaces do not block when
        # operator-authored ordering already exists.
        candidate = dict(profile)
        candidate["__item_id"] = item_id
        others = _other_non_terminal_profiles(c, project, item_id)
        dependency_pairs = load_dependency_pairs(c, item_id, others)
        overlaps = detect_overlap(
            candidate,
            others,
            dependency_pairs=dependency_pairs,
        )
        errors.extend(overlaps)

        # Step (f): strategy matrix — only for declared+apply.  Pulls
        # ``projects.breakage_policy`` (or the pre-migration default) and
        # pairs it with the profile's ``migration_strategy``.
        if profile["mutation_intent"] == MUTATION_INTENT_APPLY:
            try:
                breakage_policy = resolve_breakage_policy(c, project)
            except BreakagePolicyError as exc:
                errors.append(str(exc))
            else:
                errors.extend(
                    evaluate_strategy_matrix(
                        breakage_policy=breakage_policy,
                        profile=profile,
                    )
                )

        passed = not errors
        return GateOutcome(
            passed=passed,
            errors=errors,
            warnings=warnings,
            escalations=escalations,
        )

    if conn is not None:
        return _evaluate(conn)
    with db_helpers.connect() as owned:
        return _evaluate(owned)


__all__ = ["check_idea_to_refining_idea_gate"]
