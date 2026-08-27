"""GitHub binding payloads accept the numeric ids GitHub's API emits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yoke_core.domain.handlers.project_github_binding import (
    ProjectGithubBindingBindRequest,
    ProjectGithubBindingLifecycleRequest,
    ProjectGithubBindingStatusRequest,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


def _bind_payload(**overrides):
    payload = {
        "project": "externalwebapp",
        "installation_id": 12345,
        "repository_id": 4567,
        "github_repo": "example-org/externalwebapp",
        "expected_api_url": "https://api.github.com",
        "github_user_access_token": "github-user-token",
    }
    payload.update(overrides)
    return payload


def test_bind_accepts_numeric_github_ids_and_canonicalizes_to_text():
    parsed = ProjectGithubBindingBindRequest(**_bind_payload())

    assert parsed.installation_id == "12345"
    assert parsed.repository_id == "4567"


def test_bind_accepts_decimal_string_github_ids_unchanged():
    parsed = ProjectGithubBindingBindRequest(
        **_bind_payload(installation_id="12345", repository_id="4567")
    )

    assert parsed.installation_id == "12345"
    assert parsed.repository_id == "4567"


def test_bind_accepts_a_numeric_project_id():
    parsed = ProjectGithubBindingBindRequest(**_bind_payload(project=41))

    assert parsed.project == "41"


@pytest.mark.parametrize("rejected", [0, -1, True, 1.5, "12a", "", None])
def test_bind_refuses_values_that_are_not_positive_github_ids(rejected):
    with pytest.raises(ValidationError) as caught:
        ProjectGithubBindingBindRequest(**_bind_payload(installation_id=rejected))

    message = safe_validation_message(caught.value)
    assert "installation_id" in message
    assert "positive GitHub numeric id" in message


def test_lifecycle_accepts_the_numeric_ids_a_github_webhook_carries():
    parsed = ProjectGithubBindingLifecycleRequest(
        project=41,
        installation_id=12345,
        repository_id=4567,
        installation_status="suspended",
        repository_available=True,
    )

    assert (parsed.project, parsed.installation_id, parsed.repository_id) == (
        "41",
        "12345",
        "4567",
    )


def test_status_accepts_a_numeric_project_id():
    assert ProjectGithubBindingStatusRequest(project=41).project == "41"


def test_status_refuses_a_blank_project_reference():
    with pytest.raises(ValidationError) as caught:
        ProjectGithubBindingStatusRequest(project="   ")

    assert "project slug or numeric project id" in safe_validation_message(
        caught.value
    )
