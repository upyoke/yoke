"""Declared merge-queue GitHub config: load and diff.

The repository file ``.yoke/merge-queue.json`` is the operator-edited
source of truth for the merge-queue ruleset parameters and
``allow_auto_merge``. Doctor diffs live GitHub state against that file;
apply lives in :mod:`yoke_core.domain.merge_queue_declaration_apply`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from yoke_contracts.project_contract.merge_queue import (
    DECLARATION_RELATIVE_PATH,
    DECLARATION_SCHEMA,
)

_RULESET_BODY_KEYS = (
    "name",
    "target",
    "enforcement",
    "bypass_actors",
    "conditions",
    "rules",
)


class MergeQueueDeclarationError(ValueError):
    """Malformed or unreadable merge-queue declaration."""


def declaration_path(checkout: Path) -> Path:
    """Absolute path of the declared merge-queue file under ``checkout``."""
    return Path(checkout) / DECLARATION_RELATIVE_PATH


def load_declaration(path: Path) -> dict[str, Any]:
    """Load and lightly validate the declared merge-queue document."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MergeQueueDeclarationError(f"unreadable {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MergeQueueDeclarationError(
            f"invalid JSON in {path}: {exc}"
        ) from exc
    return validate_declaration(payload, source=str(path))


def validate_declaration(
    payload: Any,
    *,
    source: str = "merge-queue declaration",
) -> dict[str, Any]:
    """Validate declaration content already transported by a caller."""
    if not isinstance(payload, dict):
        raise MergeQueueDeclarationError(f"{source} must be a JSON object")
    schema = payload.get("schema")
    if schema != DECLARATION_SCHEMA:
        raise MergeQueueDeclarationError(
            f"{source} schema must be {DECLARATION_SCHEMA}, got {schema!r}"
        )
    ruleset = payload.get("ruleset")
    if not isinstance(ruleset, dict) or not ruleset.get("name"):
        raise MergeQueueDeclarationError(f"{source} requires ruleset.name")
    if not isinstance(ruleset.get("rules"), list) or not ruleset["rules"]:
        raise MergeQueueDeclarationError(
            f"{source} requires a non-empty ruleset.rules list"
        )
    repository = payload.get("repository")
    if not isinstance(repository, dict):
        raise MergeQueueDeclarationError(
            f"{source} requires a repository object"
        )
    if "allow_auto_merge" not in repository:
        raise MergeQueueDeclarationError(
            f"{source} requires repository.allow_auto_merge"
        )
    return dict(payload)


def _rule_by_type(
    rules: Sequence[Mapping[str, Any]], rule_type: str,
) -> Optional[dict[str, Any]]:
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == rule_type:
            return dict(rule)
    return None


def _status_contexts(parameters: Mapping[str, Any]) -> list[str]:
    checks = parameters.get("required_status_checks") or []
    contexts: list[str] = []
    if isinstance(checks, list):
        for row in checks:
            if isinstance(row, Mapping) and row.get("context"):
                contexts.append(str(row["context"]))
    return sorted(contexts)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _bypass_canonical(actors: Any) -> str:
    rows: list[dict[str, Any]] = []
    if isinstance(actors, list):
        for row in actors:
            if not isinstance(row, Mapping):
                continue
            rows.append(
                {
                    "actor_id": row.get("actor_id"),
                    "actor_type": row.get("actor_type"),
                    "bypass_mode": row.get("bypass_mode"),
                }
            )
    rows.sort(
        key=lambda r: (
            str(r.get("actor_type") or ""),
            int(r.get("actor_id") or 0),
            str(r.get("bypass_mode") or ""),
        )
    )
    return _canonical_json(rows)


def diff_declared_against_live(
    declared: Mapping[str, Any],
    *,
    live_branch_rules: Sequence[Mapping[str, Any]],
    live_allow_auto_merge: Optional[bool],
    live_bypass_actors: Any = None,
    compare_bypass: bool = False,
) -> list[str]:
    """Return human-readable drift lines; empty means declared matches live."""
    problems: list[str] = []
    ruleset = declared["ruleset"]
    declared_rules = ruleset.get("rules") or []

    live_mq = _rule_by_type(live_branch_rules, "merge_queue")
    declared_mq = _rule_by_type(declared_rules, "merge_queue")
    if declared_mq is None:
        problems.append("declared ruleset is missing a merge_queue rule")
    elif live_mq is None:
        problems.append("live branch has no merge_queue rule")
    else:
        declared_params = declared_mq.get("parameters") or {}
        live_params = live_mq.get("parameters") or {}
        if _canonical_json(declared_params) != _canonical_json(live_params):
            problems.append(
                "merge_queue parameters drifted "
                f"(declared={_canonical_json(declared_params)}; "
                f"live={_canonical_json(live_params)})"
            )

    live_rsc = _rule_by_type(live_branch_rules, "required_status_checks")
    declared_rsc = _rule_by_type(declared_rules, "required_status_checks")
    if declared_rsc is None:
        problems.append(
            "declared ruleset is missing a required_status_checks rule"
        )
    elif live_rsc is None:
        problems.append("live branch has no required_status_checks rule")
    else:
        declared_params = declared_rsc.get("parameters") or {}
        live_params = live_rsc.get("parameters") or {}
        declared_contexts = _status_contexts(declared_params)
        live_contexts = _status_contexts(live_params)
        if declared_contexts != live_contexts:
            problems.append(
                "required_status_checks contexts drifted "
                f"(declared={declared_contexts}; live={live_contexts})"
            )
        for key in (
            "strict_required_status_checks_policy",
            "do_not_enforce_on_create",
        ):
            if declared_params.get(key) != live_params.get(key):
                problems.append(
                    f"required_status_checks.{key} drifted "
                    f"(declared={declared_params.get(key)!r}; "
                    f"live={live_params.get(key)!r})"
                )

    want_auto = bool(declared["repository"]["allow_auto_merge"])
    if live_allow_auto_merge is None:
        problems.append("live allow_auto_merge could not be read")
    elif bool(live_allow_auto_merge) != want_auto:
        problems.append(
            "allow_auto_merge drifted "
            f"(declared={want_auto}; live={bool(live_allow_auto_merge)})"
        )

    if compare_bypass:
        declared_bypass = _bypass_canonical(ruleset.get("bypass_actors"))
        live_bypass = _bypass_canonical(live_bypass_actors)
        if declared_bypass != live_bypass:
            problems.append(
                "bypass_actors drifted "
                f"(declared={declared_bypass}; live={live_bypass})"
            )

    return problems


def ruleset_apply_body(ruleset: Mapping[str, Any]) -> dict[str, Any]:
    """Strip read-only fields; keep the GitHub create/update body shape."""
    body: dict[str, Any] = {}
    for key in _RULESET_BODY_KEYS:
        if key in ruleset:
            body[key] = ruleset[key]
    return body


__all__ = [
    "DECLARATION_RELATIVE_PATH",
    "DECLARATION_SCHEMA",
    "MergeQueueDeclarationError",
    "declaration_path",
    "diff_declared_against_live",
    "load_declaration",
    "ruleset_apply_body",
    "validate_declaration",
]
