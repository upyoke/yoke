"""Require a DB claim from concrete lane-only governed migration files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.db_mutation_gate_shared import _safe_parse_dict
from yoke_core.domain.migration_history import HistoryError
from yoke_core.domain.migration_merge_preflight import lane_only_migration_entries
from yoke_core.domain.migration_model_capability import (
    MigrationModelCapabilityError,
    validate,
)

ERROR_CODE = "GATE_NEW_MIGRATIONS_NEED_DB_CLAIM"


def missing_claim_errors(
    *,
    profile: Any,
    settings: Any,
    worktree_path: Path,
    integration_target: str,
    public_ref: str,
) -> list[str]:
    """Inspect every configured model, independently of declared modules."""
    if _safe_parse_dict(profile).get("state") == "declared" or not settings:
        return []
    try:
        capability = validate(
            json.loads(settings) if isinstance(settings, str) else settings
        )
        paths = set()
        for model in capability["models"].values():
            modules_dir = ((model.get("runner") or {}).get("config") or {}).get(
                "modules_dir"
            )
            if modules_dir:
                paths.update(
                    f"{modules_dir}/{name}.py"
                    for name in lane_only_migration_entries(
                        worktree_path,
                        modules_dir,
                        integration_target,
                    )
                )
    except (HistoryError, MigrationModelCapabilityError, ValueError, TypeError) as exc:
        return [
            compose_refusal(
                f"{ERROR_CODE}: migration entries could not be inspected: {exc}",
                recovery="repair migration_model settings or the lane's Git target, then retry",
            )
        ]
    if not paths:
        return []
    return [
        compose_refusal(
            "lane adds migration entries without a declared DB claim: "
            + ", ".join(sorted(paths)),
            recovery=f"run `yoke db-claim amend {public_ref}` to declare the DB claim, then retry",
        )
    ]


def check_item(item_id: int, *, db_path: str, conn: Any = None) -> dict | None:
    """Use the item's lane on this host; an unmapped host cannot inspect it."""
    from yoke_core.domain.conflict_survey import read_recorded_survey
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.db_mutation_gate_implementing import _item_lane_path
    from yoke_core.domain.db_mutation_gate_loaders import (
        _load_item_row,
        _load_capability_settings,
    )
    from yoke_core.domain.project_identity import render_item_ref

    owned = conn is None
    c = connect(db_path) if owned else conn
    try:
        lane = _item_lane_path(c, item_id)
        if lane is None:
            return None
        item = _load_item_row(c, item_id)
        settings = _load_capability_settings(c, item["project"])
        survey = read_recorded_survey(c, item_id) or {}
        errors = missing_claim_errors(
            profile=item.get("db_mutation_profile"),
            settings=settings,
            worktree_path=lane,
            integration_target=str(survey.get("integration_target") or "main"),
            public_ref=render_item_ref(c, item_id),
        )
        return (
            {"success": False, "error_code": ERROR_CODE, "error": "\n".join(errors)}
            if errors
            else None
        )
    finally:
        if owned:
            c.close()
