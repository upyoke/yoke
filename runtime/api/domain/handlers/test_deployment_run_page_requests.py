"""Dedicated Runs-page request validation and service scoping."""

from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_core.domain.deployment_run_history_read import RunHistoryCursorError
from yoke_core.domain.handlers.deployment_common import DeploymentRunListRequest
from yoke_core.domain.handlers.deployment_runs import handle_deployment_run_list


class _Connection:
    def close(self):
        return None


def _request(payload, actor_id=None):
    return deployment_request(
        function="deployment_runs.list",
        payload=payload,
        actor_id=actor_id,
    )


def test_page_shape_cannot_mix_with_legacy_list_inputs():
    outcome = handle_deployment_run_list(
        _request(
            {
                "page": {"page_size": 50},
                "limit": 20,
            }
        )
    )

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "reload the first Runs page" in outcome.error.message
    assert outcome.error.jsonpath == "$.payload.page"


def test_registered_request_model_preserves_the_opt_in_page():
    payload = DeploymentRunListRequest.model_validate(
        {"page": {"page_size": 50, "search": "VIS-17"}}
    ).model_dump(exclude_none=True)

    assert payload == {"page": {"page_size": 50, "search": "VIS-17"}}


def test_page_must_be_an_object_with_only_named_criteria():
    for page in (None, {"unknown_filter": "value"}):
        outcome = handle_deployment_run_list(_request({"page": page}))

        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "reload the first Runs page" in outcome.error.message


def test_page_shape_resolves_actor_visible_projects_before_the_read():
    result = {
        "fields": [],
        "rows": [],
        "limit": 50,
        "unfinished_count": 0,
        "completed_match_count": 0,
        "completed_loaded_count": 0,
        "next_cursor": None,
        "filters": {},
    }
    connection = _Connection()
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=connection,
        ),
        patch(
            "yoke_core.domain.handlers.items_project_scope.actor_visible_scope",
            return_value={1, 2},
        ),
        patch(
            "yoke_core.domain.handlers.items_project_scope.resolve_visible_project_ids",
            return_value=[2],
        ) as resolve,
        patch(
            "yoke_core.domain.deployment_run_history_read.read_deployment_run_history",
            return_value=result,
        ) as read,
    ):
        outcome = handle_deployment_run_list(
            _request(
                {
                    "page": {
                        "projects": ["2", "invisible"],
                        "search": "YOK-9",
                        "status": "failed",
                        "environment": "prod",
                        "flow": "hosted-release",
                        "page_size": 50,
                    },
                },
                actor_id="41",
            )
        )

    assert outcome.primary_success
    resolve.assert_called_once_with(
        connection,
        ["2", "invisible"],
        {1, 2},
    )
    assert read.call_args.kwargs == {
        "project_ids": [2],
        "search": "YOK-9",
        "status": "failed",
        "environment": "prod",
        "flow": "hosted-release",
        "page_size": 50,
        "cursor": None,
        "actor_id": 41,
    }


def test_page_shape_names_malformed_cursor_and_recovery():
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Connection(),
        ),
        patch(
            "yoke_core.domain.handlers.items_project_scope.actor_visible_scope",
            return_value=None,
        ),
        patch(
            "yoke_core.domain.deployment_run_history_read.read_deployment_run_history",
            side_effect=RunHistoryCursorError(
                "Runs page cursor is malformed. Reload the first Runs page without a cursor."
            ),
        ),
    ):
        outcome = handle_deployment_run_list(
            _request(
                {
                    "page": {"cursor": "broken"},
                }
            )
        )

    assert not outcome.primary_success
    assert outcome.error.code == "invalid_cursor"
    assert "Reload the first Runs page" in outcome.error.message
    assert outcome.error.jsonpath == "$.payload.page.cursor"


def test_page_validation_bounds_transfer_and_names_recovery():
    outcome = handle_deployment_run_list(
        _request(
            {
                "page": {"page_size": 101},
            }
        )
    )

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "reload the first Runs page" in outcome.error.message
    assert outcome.error.jsonpath.endswith("page_size")
