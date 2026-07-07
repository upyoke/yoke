"""Read-only GitHub Actions self-hosted runner status handler."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import json_helper
from yoke_core.domain.github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    DEFAULT_RUNNER_LABELS,
    DEFAULT_RUNS_ON_VARIABLE,
    RunnerFleetSettings,
    RunnerFleetSettingsError,
    load_json_string,
)
from yoke_core.domain.handlers.github_actions_set import (
    _bad_request,
    _transport_failed,
    _validate_and_resolve,
)
from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_get_settings,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


DEFAULT_REQUIRED_LABELS = DEFAULT_RUNNER_LABELS


class RunnersStatusRequest(BaseModel):
    repo: Optional[str] = Field(
        None,
        min_length=3,
        description=(
            "GitHub repo slug. When omitted, the runner-fleet capability "
            "must provide it."
        ),
    )
    required_labels: List[str] = Field(
        default_factory=list,
        description=(
            "Labels that must all be present on a usable runner. When "
            "empty, the runner-fleet capability supplies them."
        ),
    )
    variable_name: str = Field(
        "",
        description=(
            "Actions variable that routes workflow runs-on. When omitted, "
            "the runner-fleet capability supplies it."
        ),
    )
    project: str = Field("yoke", description="Project capability owning the PAT.")
    runner_capability: str = Field(
        RUNNER_FLEET_CAPABILITY_TYPE,
        min_length=1,
        description="Project capability type holding runner fleet settings.",
    )


class RunnerSummary(BaseModel):
    id: int
    name: str
    status: str
    busy: bool
    labels: List[str]


class RunnersStatusResponse(BaseModel):
    repo: str
    required_labels: List[str]
    recommended_value: str
    variable_name: str
    runner_capability: str
    capability_configured: bool
    provider: str
    desired_runner_count: int
    max_runner_count: int
    instance_type: str
    root_volume_gb: int
    variable_exists: bool
    variable_value: Optional[str] = None
    runner_count: int
    matching_count: int
    online_matching_count: int
    idle_matching_count: int
    ready: bool
    action: str
    message: str
    runners: List[RunnerSummary]


def handle_runners_status(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request, RunnersStatusRequest, "github_actions.runners.status",
    )
    if err is not None:
        return err
    assert payload is not None
    assert token is not None

    settings, capability_configured, err = _resolve_runner_fleet_settings(payload)
    if err is not None:
        return err
    repo = (payload.repo or settings.repo or "").strip()
    if "/" not in repo:
        return _bad_request(
            "repo must be owner/name, either as an argument or in the "
            f"{payload.runner_capability!r} capability settings",
            jsonpath="$.payload.repo",
        )
    variable_name = (payload.variable_name or settings.variable_name).strip()
    required = _clean_labels(payload.required_labels or settings.runner_labels)

    from yoke_core.domain import github_variables_rest
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get

    try:
        data = rest_get(
            f"/repos/{repo}/actions/runners",
            query={"per_page": "100"},
            token=token,
        )
        variable_value = github_variables_rest.get_repo_variable(
            repo, variable_name, token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"runners status failed: {exc}")

    runners = _runner_summaries(data)
    recommended = _runs_on_value(required)
    matching = [runner for runner in runners if _has_labels(runner, required)]
    online = [runner for runner in matching if runner.status == "online"]
    idle = [runner for runner in online if not runner.busy]
    action, message = _classify(
        matching_count=len(matching),
        online_count=len(online),
        variable_value=variable_value,
        recommended_value=recommended,
    )
    response = RunnersStatusResponse(
        repo=repo,
        required_labels=required,
        recommended_value=recommended,
        variable_name=variable_name,
        runner_capability=payload.runner_capability,
        capability_configured=capability_configured,
        provider=settings.provider,
        desired_runner_count=settings.desired_runner_count,
        max_runner_count=settings.max_runner_count,
        instance_type=settings.instance.instance_type,
        root_volume_gb=settings.instance.root_volume_gb,
        variable_exists=variable_value is not None,
        variable_value=variable_value,
        runner_count=len(runners),
        matching_count=len(matching),
        online_matching_count=len(online),
        idle_matching_count=len(idle),
        ready=bool(online and variable_value == recommended),
        action=action,
        message=message,
        runners=runners,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def _resolve_runner_fleet_settings(
    payload: RunnersStatusRequest,
) -> tuple[RunnerFleetSettings, bool, Optional[HandlerOutcome]]:
    needs_settings = (
        not payload.repo or not payload.required_labels or not payload.variable_name
    )
    if not needs_settings:
        return RunnerFleetSettings(), False, None
    try:
        raw = cmd_capability_get_settings(payload.project, payload.runner_capability)
        return load_json_string(raw), raw is not None, None
    except (RunnerFleetSettingsError, ValueError) as exc:
        return (
            RunnerFleetSettings(),
            False,
            _bad_request(str(exc), jsonpath="$.payload.runner_capability"),
        )


def _runner_summaries(data: object) -> List[RunnerSummary]:
    body = data if isinstance(data, dict) else {}
    entries = body.get("runners")
    if not isinstance(entries, list):
        entries = []
    runners: List[RunnerSummary] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        runners.append(
            RunnerSummary(
                id=int(entry.get("id") or 0),
                name=str(entry.get("name") or ""),
                status=str(entry.get("status") or ""),
                busy=bool(entry.get("busy")),
                labels=_label_names(entry.get("labels")),
            )
        )
    return runners


def _label_names(raw: object) -> List[str]:
    if not isinstance(raw, list):
        return []
    names: List[str] = []
    for label in raw:
        if isinstance(label, dict):
            value = str(label.get("name") or "").strip()
            if value:
                names.append(value)
    return names


def _clean_labels(labels: List[str]) -> List[str]:
    result: List[str] = []
    for label in labels:
        cleaned = label.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result or list(DEFAULT_REQUIRED_LABELS)


def _has_labels(runner: RunnerSummary, required: List[str]) -> bool:
    available = {label.lower() for label in runner.labels}
    return all(label.lower() in available for label in required)


def _runs_on_value(labels: List[str]) -> str:
    return json_helper.dumps_compact(labels)


def _classify(
    *,
    matching_count: int,
    online_count: int,
    variable_value: Optional[str],
    recommended_value: str,
) -> tuple[str, str]:
    if matching_count == 0:
        return "register_runner", "No registered runner has all required labels."
    if online_count == 0:
        return "start_runner", "Matching runners exist, but none are online."
    if variable_value != recommended_value:
        return "set_variable", "Matching online runner exists; set the runner variable."
    return "ready", "Matching online runner exists and the runner variable is armed."


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.runners.status",
        "handler": handle_runners_status,
        "request_model": RunnersStatusRequest,
        "response_model": RunnersStatusResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_runners",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "DEFAULT_REQUIRED_LABELS",
    "DEFAULT_RUNS_ON_VARIABLE",
    "REGISTRATIONS",
    "RunnersStatusRequest",
    "RunnersStatusResponse",
    "handle_runners_status",
]
