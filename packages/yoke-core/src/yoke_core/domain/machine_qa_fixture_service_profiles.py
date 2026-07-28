"""Closed fake-Yoke API profiles for Machine QA fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from yoke_core.domain.machine_qa_fixture_constants import FAKE_TOKEN_PATH


@dataclass(frozen=True)
class FakeServiceVariant:
    """One exact fake-service request and its response profile."""

    parameters: Mapping[str, Any]
    payload: Mapping[str, Any]


_APPLY_PROJECT_ERRORS = {
    "projects.get": {
        "code": "not_found",
        "message": "project not found",
    },
    "projects.create": {
        "code": "permission_denied",
        "message": "permission denied for org acme",
    },
}
_STATE_MISSING_PROJECT_ERROR = {
    "projects.get": {
        "code": "not_found",
        "message": "project 404 was not found",
    },
}
_APPLY_DELAY = {"onboard.checklist.run": 6}


def _identity(
    *,
    actor: str,
    orgs: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "actor": {"label": actor},
        "orgs": orgs,
        "projects": projects,
    }


_SUCCESS_IDENTITY = _identity(
    actor="recipe actor",
    orgs=[{"name": "recipe-org", "roles": ["owner"]}],
    projects=[{"name": "recipe-project", "roles": ["admin"]}],
)
_NO_ACCESS_IDENTITY = _identity(
    actor="no-access actor",
    orgs=[],
    projects=[],
)
_MANY_ACCESS_IDENTITY = _identity(
    actor="many-access actor",
    orgs=[
        {"name": f"o{index}", "roles": [role]}
        for index, role in enumerate(
            ("owner", "viewer", "operator", "viewer", "viewer", "viewer"),
            start=1,
        )
    ],
    projects=[
        {"name": f"p{index}", "roles": [role]}
        for index, role in enumerate(
            ("admin", "viewer", "operator", "viewer", "viewer", "viewer"),
            start=1,
        )
    ],
)
_SOURCE_DEV_PROJECT = {
    "id": 1,
    "slug": "yoke",
    "name": "Yoke",
    "roles": ["admin"],
}
_SOURCE_DEV_ACCESS = {
    **_identity(
        actor="source-dev recipe actor",
        orgs=[{"name": "recipe-org", "roles": ["owner"]}],
        projects=[_SOURCE_DEV_PROJECT],
    ),
    "function_rows": [{"id": 1, "slug": "yoke", "name": "Yoke"}],
}
_SOURCE_DEV_NO_ACCESS = {
    **_identity(
        actor="source-dev recipe actor",
        orgs=[{"name": "recipe-org", "roles": ["owner"]}],
        projects=[
            {
                "id": 2,
                "slug": "other",
                "name": "Other project",
                "roles": ["viewer"],
            }
        ],
    ),
    "function_rows": [],
}
_APPLY_PROJECT = {
    "id": 91,
    "slug": "apply-recipe",
    "name": "Apply Recipe",
    "github_repo": "owner/apply-recipe",
    "default_branch": "main",
    "public_item_prefix": "APL",
}
_APPLY_BASE = {
    **_identity(
        actor="apply recipe actor",
        orgs=[{"name": "recipe-org", "roles": ["owner"]}],
        projects=[],
    ),
    "project": _APPLY_PROJECT,
}
_PROJECT_META_FAILURE = {
    **_identity(
        actor="project-meta recipe actor",
        orgs=[{"name": "recipe-org", "roles": ["owner"]}],
        projects=[],
    ),
    "function_errors": {
        "board.data.get": {
            "code": "board_data_unavailable",
            "message": "board data unavailable for recipe",
        },
    },
}


def _state_project_payload(
    project_id: int,
    *,
    function_errors: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    project = {
        "id": project_id,
        "slug": "state-project-one",
        "name": "State Project One",
        "github_repo": "state/project-one",
        "default_branch": "main",
        "public_item_prefix": "STA",
    }
    return {
        **_identity(
            actor="stored-state recipe actor",
            orgs=[{"name": "recipe-org", "roles": ["owner"]}],
            projects=[{"name": project["name"], "roles": ["admin"]}],
        ),
        "project": project,
        "function_rows": [project],
        "function_errors": dict(function_errors or {}),
    }


def _parameters(
    profile: str,
    port: int,
    **optional: Any,
) -> dict[str, Any]:
    return {
        "bind_host": "127.0.0.1",
        "port": port,
        "profile": profile,
        "token_path": FAKE_TOKEN_PATH,
        **optional,
    }


def _variant(
    profile: str,
    port: int,
    payload: Mapping[str, Any],
    **optional: Any,
) -> FakeServiceVariant:
    return FakeServiceVariant(
        parameters=MappingProxyType(_parameters(profile, port, **optional)),
        payload=MappingProxyType(dict(payload)),
    )


_variants: dict[tuple[str, int], FakeServiceVariant] = {
    ("identity-success", 19087): _variant(
        "identity-success",
        19087,
        _SUCCESS_IDENTITY,
    ),
    ("identity-no-access", 19088): _variant(
        "identity-no-access",
        19088,
        _NO_ACCESS_IDENTITY,
    ),
    ("identity-many-access", 19089): _variant(
        "identity-many-access",
        19089,
        _MANY_ACCESS_IDENTITY,
    ),
    ("project-meta-board-data-failure", 19109): _variant(
        "project-meta-board-data-failure",
        19109,
        _PROJECT_META_FAILURE,
    ),
    ("source-dev-no-access", 19107): _variant(
        "source-dev-no-access",
        19107,
        _SOURCE_DEV_NO_ACCESS,
    ),
}
for _port in (19106, 19112, 19114, 19116, 19118, 19120):
    _variants[("source-dev-access", _port)] = _variant(
        "source-dev-access",
        _port,
        _SOURCE_DEV_ACCESS,
    )
for _port in (19120, 19122):
    _variants[("apply", _port)] = _variant("apply", _port, _APPLY_BASE)
_variants[("apply", 19119)] = _variant(
    "apply",
    19119,
    {**_APPLY_BASE, "function_errors": _APPLY_PROJECT_ERRORS},
    function_errors=_APPLY_PROJECT_ERRORS,
)
_variants[("apply", 19123)] = _variant(
    "apply",
    19123,
    {**_APPLY_BASE, "function_delays": _APPLY_DELAY},
    function_delays=_APPLY_DELAY,
)
_variants[("apply-board-art-conflict", 19121)] = _variant(
    "apply-board-art-conflict",
    19121,
    {**_APPLY_BASE, "install_bundle_board_art_conflict": True},
)
for _port, _project_id, _errors in (
    (19124, 101, None),
    (19125, 101, None),
    (19126, 404, _STATE_MISSING_PROJECT_ERROR),
):
    _optional: dict[str, Any] = {"project_id": _project_id}
    if _errors:
        _optional["function_errors"] = _errors
    _variants[("state-project", _port)] = _variant(
        "state-project",
        _port,
        _state_project_payload(_project_id, function_errors=_errors),
        **_optional,
    )

FAKE_SERVICE_VARIANTS: Mapping[
    tuple[str, int],
    FakeServiceVariant,
] = MappingProxyType(_variants)


__all__ = [
    "FAKE_SERVICE_VARIANTS",
    "FakeServiceVariant",
]
