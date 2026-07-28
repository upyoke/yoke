"""Repository and assertion validators for Machine QA fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.machine_qa_fixture_constants import (
    APPLY_RESUME_PATH,
    FAKE_TOKEN_PATH,
    SOURCE_DEV_GIT_CONFIG_PATH,
    SOURCE_DEV_REMOTE_PATH,
    SOURCE_DEV_REPORT_PATH,
)
from yoke_core.domain.machine_qa_fixture_validation_common import (
    Validator,
    bounded_integer,
    bounded_text,
    exact_keys,
    operation_error,
)
from yoke_core.domain.machine_qa_fixture_validation_constants import (
    COMPLETED_APPLY_STEPS,
    GENERIC_CHECKOUTS,
    REMOTE_FIXTURES,
    SOURCE_DEV_ORIGIN,
    SOURCE_DEV_PATH_STATES,
    SOURCE_DEV_SEED_PATH,
    STATE_PROJECTS,
    TERMINAL_SIZES,
)


def _git_checkout(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.git-checkout-prepare"
    exact_keys(
        operation_id,
        parameters,
        {"default_branch", "path", "readme_text", "state"},
        {"origin"},
    )
    path = bounded_text(operation_id, parameters, "path")
    expected = GENERIC_CHECKOUTS.get(path)
    candidate = (
        parameters.get("state"),
        parameters.get("default_branch"),
        parameters.get("readme_text"),
    )
    if expected is None or candidate != expected:
        raise operation_error(
            operation_id,
            "checkout variant is not registered",
        )
    origin = parameters.get("origin")
    if origin is not None and origin != SOURCE_DEV_ORIGIN:
        raise operation_error(operation_id, "origin is not registered")
    result = {
        "default_branch": expected[1],
        "path": path,
        "readme_text": expected[2],
        "state": expected[0],
    }
    if origin is not None:
        result["origin"] = origin
    return result


def _git_remote(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.git-remote-prepare"
    exact_keys(operation_id, parameters, {"branch", "name", "path", "url"})
    name = bounded_text(operation_id, parameters, "name")
    registered = REMOTE_FIXTURES.get(name)
    if registered is None:
        raise operation_error(operation_id, "remote name is not registered")
    branch, path = registered
    expected = {
        "branch": branch,
        "name": name,
        "path": path,
        "url": f"file://{path}",
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "remote parameters do not match its name",
        )
    return expected


def _source_dev_checkout(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.source-dev-checkout-prepare"
    exact_keys(operation_id, parameters, {"origin", "path", "state"})
    path = bounded_text(operation_id, parameters, "path")
    expected_state = SOURCE_DEV_PATH_STATES.get(path)
    if (
        expected_state is None
        or parameters.get("state") != expected_state
        or parameters.get("origin") != SOURCE_DEV_ORIGIN
    ):
        raise operation_error(
            operation_id,
            "source checkout variant is not registered",
        )
    return {
        "origin": SOURCE_DEV_ORIGIN,
        "path": path,
        "state": expected_state,
    }


def _source_dev_remote(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.source-dev-remote-prepare"
    expected = {
        "default_branch": "main",
        "git_config_path": SOURCE_DEV_GIT_CONFIG_PATH,
        "remote_path": SOURCE_DEV_REMOTE_PATH,
        "remote_url": f"file://{SOURCE_DEV_REMOTE_PATH}",
        "seed_path": SOURCE_DEV_SEED_PATH,
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "source remote does not match the closed fixture",
        )
    return expected


def _project_registrations(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.project-registrations-prepare"
    exact_keys(operation_id, parameters, {"config_path", "projects"})
    if parameters.get("config_path") != "~/.yoke/config.json":
        raise operation_error(
            operation_id,
            "config_path is not product-owned",
        )
    projects = parameters.get("projects")
    if not isinstance(projects, list) or not 1 <= len(projects) <= 2:
        raise operation_error(
            operation_id,
            "projects must contain one or two rows",
        )
    normalized = []
    seen: set[str] = set()
    for project in projects:
        if not isinstance(project, Mapping) or set(project) != {
            "path",
            "project_id",
        }:
            raise operation_error(
                operation_id,
                "project rows require path and project_id",
            )
        path = project.get("path")
        project_id = project.get("project_id")
        if (
            not isinstance(path, str)
            or STATE_PROJECTS.get(path) != project_id
            or path in seen
        ):
            raise operation_error(
                operation_id,
                "project row is not registered",
            )
        seen.add(path)
        normalized.append({"path": path, "project_id": project_id})
    return {
        "config_path": "~/.yoke/config.json",
        "projects": normalized,
    }


def _apply_resume(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "fixture.apply-resume-report-prepare"
    expected = {
        "api_url": "http://127.0.0.1:19122",
        "completed_steps": COMPLETED_APPLY_STEPS,
        "path": APPLY_RESUME_PATH,
        "run_id": "run-apply-resume",
        "token_path": FAKE_TOKEN_PATH,
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "report inputs do not match the resume fixture",
        )
    return expected


def _terminal_size(parameters: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = "terminal.size-prepare"
    exact_keys(operation_id, parameters, {"columns", "rows"})
    columns = bounded_integer(
        operation_id,
        parameters,
        "columns",
        minimum=1,
        maximum=500,
    )
    rows = bounded_integer(
        operation_id,
        parameters,
        "rows",
        minimum=1,
        maximum=500,
    )
    if (columns, rows) not in TERMINAL_SIZES:
        raise operation_error(
            operation_id,
            "terminal size is not registered",
        )
    return {"columns": columns, "rows": rows}


def _checkout_state_assertion(
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    operation_id = "source-dev.checkout-state-assert"
    fresh_path = next(
        path for path in SOURCE_DEV_PATH_STATES if path.endswith("-fresh")
    )
    expected = {
        "apply_report_path": SOURCE_DEV_REPORT_PATH,
        "checkout_path": fresh_path,
        "expected_branch": "main",
        "expected_origin": SOURCE_DEV_ORIGIN,
        "forbid_product_copy_directories": True,
        "require_git_history": True,
        "require_git_hooks": True,
        "require_source_links": True,
    }
    if dict(parameters) != expected:
        raise operation_error(
            operation_id,
            "assertion does not match the source fixture",
        )
    return expected


REPOSITORY_SETUP_VALIDATORS: dict[str, Validator] = {
    "fixture.apply-resume-report-prepare": _apply_resume,
    "fixture.git-checkout-prepare": _git_checkout,
    "fixture.git-remote-prepare": _git_remote,
    "fixture.project-registrations-prepare": _project_registrations,
    "fixture.source-dev-checkout-prepare": _source_dev_checkout,
    "fixture.source-dev-remote-prepare": _source_dev_remote,
    "terminal.size-prepare": _terminal_size,
}
POST_VALIDATORS: dict[str, Validator] = {
    "source-dev.checkout-state-assert": _checkout_state_assertion,
}


__all__ = [
    "POST_VALIDATORS",
    "REPOSITORY_SETUP_VALIDATORS",
]
