"""The registered read behind the Project settings lane summary.

The summary shows what routing will actually do, which is a different
document from the one stored: defaults sit underneath a partial stored
capability, lane labels and glyphs fall back when unset, and "which
harnesses land here by default" is the answer to running each harness
through the resolver rather than a key anyone typed. Composing that in the
browser would mean a second implementation of precedence, so it is
composed here and the page renders what it is handed.

The result also carries the action catalog, so a lane's allowlist can be
shown with each action's label and description without the page holding a
list that drifts from the one validation and dispatch use.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.executor_labels import (
    CANONICAL_HARNESS_IDS,
    harness_display_name,
)
from yoke_contracts.session_lane import lane_is_unresolved, lane_presentation
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.routable_actions import routable_action_catalog_payload


class LaneSummaryGetRequest(BaseModel):
    """Select one project's effective lane routing summary."""

    model_config = ConfigDict(extra="forbid")

    project: str


class LaneSummaryResponse(BaseModel):
    project: str
    project_id: int
    configured: bool
    lanes: List[Dict[str, Any]]
    unrouted_harnesses: List[str]
    action_catalog: List[Dict[str, str]]
    harnesses: List[Dict[str, str]]


def _authorized_project_ref(request: FunctionCallRequest, payload_project: str) -> str:
    """Prefer the concrete project identity resolved by authorization."""
    authorized = (request.options or {}).get("authorized_project_id")
    if authorized is None:
        return payload_project
    return str(int(authorized))


def _declared_lanes(config: Any) -> tuple[str, ...]:
    """Return every lane the effective configuration can route onto.

    Ordered so the summary reads the same on every load: the lanes with a
    declared allowlist first in their configured order, then any lane that
    only a rule or a harness default names.
    """
    ordered: List[str] = list(config.lane_allowed_paths)
    for lane in (
        *config.executor_default_lanes.values(),
        *config.executor_wildcard_lanes.values(),
        *(rule.lane for rule in config.lane_rules),
        *config.lane_metadata,
    ):
        if lane and lane not in ordered:
            ordered.append(lane)
    return tuple(ordered)


def _harness_defaults(config: Any) -> tuple[Dict[str, List[str]], List[str]]:
    """Resolve where each harness lands with no model attested.

    Run through the resolver rather than read off ``executor_default_lanes``:
    a harness-only rule is as much a default as that key is, and only the
    resolver knows which of them wins. A harness that resolves to the
    unresolved sentinel lands on no lane at all, and is returned separately
    so the page can say so — otherwise it would simply be absent from every
    row, which reads like a lane nobody defaults to rather than a harness
    that cannot be routed.
    """
    by_lane: Dict[str, List[str]] = {}
    unrouted: List[str] = []
    for harness_id in CANONICAL_HARNESS_IDS:
        lane = config.lane_for_session(executor=harness_id)
        label = harness_display_name(harness_id)
        if lane_is_unresolved(lane):
            unrouted.append(label)
            continue
        by_lane.setdefault(lane, []).append(label)
    return by_lane, unrouted


def _lane_rows(
    config: Any, settings: Dict[str, Any], defaults_by_lane: Dict[str, List[str]]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for lane in _declared_lanes(config):
        presentation = lane_presentation(lane, settings)
        rows.append(
            {
                "id": lane,
                "label": presentation["label"],
                "glyph": presentation["glyph"],
                "actions": list(config.lane_allowed_paths.get(lane, [])),
                "matches": [
                    rule.as_payload()
                    for rule in config.lane_rules
                    if rule.lane == lane
                ],
                "default_for": defaults_by_lane.get(lane, []),
            }
        )
    return rows


def handle_lane_summary_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the project's effective lane routing, ready to render."""
    try:
        parsed = LaneSummaryGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")

    from yoke_core.api.routing_config import (
        load_project_routing_settings,
        load_routing_config,
    )
    from yoke_core.domain import json_helper
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_get_settings,
    )
    from yoke_contracts.project_contract.project_keys import (
        SESSION_ROUTING_CAPABILITY,
    )

    project_ref = _authorized_project_ref(request, parsed.project)
    try:
        stored = cmd_capability_get_settings(project_ref, SESSION_ROUTING_CAPABILITY)
        with connect() as conn:
            project_id = resolve_project_id(conn, project_ref)
            raw_settings = load_project_routing_settings(conn, project_id)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")

    config = load_routing_config("", project_settings=raw_settings)
    settings = _stored_settings(stored, json_helper)
    defaults_by_lane, unrouted = _harness_defaults(config)
    return HandlerOutcome(
        result_payload={
            "project": parsed.project,
            "project_id": project_id,
            "configured": stored is not None,
            "lanes": _lane_rows(config, settings, defaults_by_lane),
            "unrouted_harnesses": unrouted,
            "action_catalog": routable_action_catalog_payload(),
            "harnesses": [
                {"id": harness_id, "label": harness_display_name(harness_id)}
                for harness_id in CANONICAL_HARNESS_IDS
            ],
        }
    )


def _stored_settings(stored: Optional[str], json_helper: Any) -> Dict[str, Any]:
    """Return the stored document as a mapping, or empty when unreadable."""
    if not stored:
        return {}
    try:
        parsed = json_helper.loads_text(stored)
    except Exception:  # noqa: BLE001 - presentation must survive a bad row
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "LaneSummaryGetRequest",
    "LaneSummaryResponse",
    "handle_lane_summary_get",
]
