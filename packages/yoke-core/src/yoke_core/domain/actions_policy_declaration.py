"""Declared repository Actions policies: validate, shape and diff.

``.yoke/merge-queue.json`` may carry an ``actions_policies`` list. Its
presence hands every repository-level Actions policy to the declaration:
apply creates or updates each declared policy by name and deletes any
repository policy the list does not name, and Doctor reports the same
difference as drift. Without the key Yoke leaves Actions policies alone.

The motivating rule is GitHub blocking ``pull_request_target`` in public
repositories unless an event policy allows it; a required check that runs
on that event never reports without one.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

ACTIONS_POLICIES_KEY = "actions_policies"
POLICY_ENFORCEMENTS = ("active", "disabled", "evaluate")
_POLICY_BODY_KEYS = ("name", "enforcement", "conditions", "rules")


class ActionsPolicyDeclarationError(ValueError):
    """Malformed ``actions_policies`` declaration."""


def declares_actions_policies(declared: Mapping[str, Any]) -> bool:
    """Whether the declaration owns the repository's Actions policies."""
    return ACTIONS_POLICIES_KEY in declared


def validate_actions_policies(value: Any, *, source: str) -> list[dict[str, Any]]:
    """Validate the declared policy list; names must be unique."""
    if not isinstance(value, list):
        raise ActionsPolicyDeclarationError(
            f"{source} {ACTIONS_POLICIES_KEY} must be a list"
        )
    seen: set[str] = set()
    policies: list[dict[str, Any]] = []
    for index, policy in enumerate(value):
        where = f"{source} {ACTIONS_POLICIES_KEY}[{index}]"
        if not isinstance(policy, dict):
            raise ActionsPolicyDeclarationError(f"{where} must be an object")
        name = policy.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ActionsPolicyDeclarationError(f"{where} requires a name")
        if name in seen:
            raise ActionsPolicyDeclarationError(
                f"{where} repeats policy name {name!r}"
            )
        seen.add(name)
        if policy.get("enforcement") not in POLICY_ENFORCEMENTS:
            raise ActionsPolicyDeclarationError(
                f"{where} enforcement must be one of {list(POLICY_ENFORCEMENTS)}"
            )
        if not isinstance(policy.get("conditions", {}), dict):
            raise ActionsPolicyDeclarationError(f"{where} conditions must be an object")
        rules = policy.get("rules")
        if not isinstance(rules, list) or not rules or not all(
            isinstance(rule, dict) and rule.get("type") for rule in rules
        ):
            raise ActionsPolicyDeclarationError(
                f"{where} requires a non-empty rules list of typed rules"
            )
        policies.append(dict(policy))
    return policies


def policy_body(policy: Mapping[str, Any]) -> dict[str, Any]:
    """The GitHub create/update body for one declared policy."""
    body = {key: policy[key] for key in _POLICY_BODY_KEYS if key in policy}
    body.setdefault("conditions", {})
    return body


def _canonical(value: Any) -> Any:
    """Order-insensitive form: GitHub returns string lists sorted."""
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _rules_shape(rules: Any) -> Any:
    rows = rules if isinstance(rules, list) else []
    return _canonical(
        [
            {"type": row.get("type"), "parameters": row.get("parameters") or {}}
            for row in rows
            if isinstance(row, Mapping)
        ]
    )


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def policy_drift(
    declared: Mapping[str, Any], live: Mapping[str, Any],
) -> list[str]:
    """Drift lines for one declared policy against its live detail."""
    name = declared["name"]
    problems: list[str] = []
    if declared.get("enforcement") != live.get("enforcement"):
        problems.append(
            f"actions policy {name!r} enforcement drifted "
            f"(declared={declared.get('enforcement')!r}; "
            f"live={live.get('enforcement')!r})"
        )
    declared_conditions = _canonical(declared.get("conditions") or {})
    live_conditions = _canonical(live.get("conditions") or {})
    if declared_conditions != live_conditions:
        problems.append(
            f"actions policy {name!r} conditions drifted "
            f"(declared={_compact(declared_conditions)}; "
            f"live={_compact(live_conditions)})"
        )
    declared_rules = _rules_shape(declared.get("rules"))
    live_rules = _rules_shape(live.get("rules"))
    if declared_rules != live_rules:
        problems.append(
            f"actions policy {name!r} rules drifted "
            f"(declared={_compact(declared_rules)}; live={_compact(live_rules)})"
        )
    return problems


def diff_policies(
    declared: Sequence[Mapping[str, Any]],
    live: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Drift between declared policies and live repository policy details."""
    live_by_name = {str(row.get("name") or ""): row for row in live}
    problems: list[str] = []
    for policy in declared:
        row = live_by_name.get(policy["name"])
        if row is None:
            problems.append(f"actions policy {policy['name']!r} is missing live")
        else:
            problems.extend(policy_drift(policy, row))
    declared_names = {policy["name"] for policy in declared}
    for name, row in sorted(live_by_name.items()):
        if name not in declared_names:
            problems.append(
                f"live actions policy {name!r} (id={row.get('id')}) is not declared"
            )
    return problems


__all__ = [
    "ACTIONS_POLICIES_KEY",
    "POLICY_ENFORCEMENTS",
    "ActionsPolicyDeclarationError",
    "declares_actions_policies",
    "diff_policies",
    "policy_body",
    "policy_drift",
    "validate_actions_policies",
]
