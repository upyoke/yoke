"""Browser scheme authoring, payload and failure evidence boundaries."""

from contextlib import ExitStack
import json
from unittest import mock

import pytest

from yoke_contracts.browser_qa_contract import (
    case_color_scheme,
    BrowserMethodContractViolation,
)
from yoke_core.domain import browser_client, browser_qa
from yoke_core.domain.browser_qa_case_config import color_scheme_failure
from yoke_core.domain.qa_method_config_validation import (
    validate_method_config,
    QaMethodConfigError,
)
from runtime.api.domain.browser_qa_test_helpers import (
    _patch_external_deps,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db, connect_test_db


@pytest.mark.parametrize("value", ["sepia", "", None, True, 1, [], {}])
def test_invalid_scheme_is_refused_during_authoring(value):
    config = {
        "color_scheme": value,
        "steps": [
            {"action": "navigate", "route": "/"},
            {"action": "assert", "target": "h1", "check": "visible"},
        ],
    }
    assert isinstance(case_color_scheme(config), BrowserMethodContractViolation)
    with pytest.raises(QaMethodConfigError, match="case_color_scheme_invalid.*omit"):
        validate_method_config("browser-check", config)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_page_open_carries_request_and_requires_observed_response(scheme):
    with mock.patch.object(
        browser_client,
        "daemon_request",
        return_value={
            "data": {
                "pageId": "owned",
                "color_scheme": {"requested": scheme, "observed": scheme},
            },
        },
    ) as request:
        assert (
            browser_client.open_owned_page(
                {"width": 400, "height": 600}, color_scheme=scheme
            )
            == "owned"
        )
    assert request.call_args.args[1]["colorScheme"] == scheme


def test_missing_open_observation_closes_page_and_refuses():
    with mock.patch.object(
        browser_client, "daemon_request", return_value={"data": {"pageId": "owned"}}
    ) as request:
        with pytest.raises(RuntimeError, match="color_scheme_observation_missing"):
            browser_client.open_owned_page(
                {"width": 400, "height": 600}, color_scheme="dark"
            )
    assert request.call_args.args[1] == {"pageId": "owned"}


@pytest.mark.parametrize(
    "evidence,code",
    [
        (None, "color_scheme_observation_missing"),
        ({"requested": "dark", "observed": "light"}, "color_scheme_mismatch"),
        ({"requested": "light", "observed": "dark"}, "color_scheme_mismatch"),
    ],
)
def test_unobserved_or_mismatched_steps_cannot_credit_evidence(
    tmp_path, evidence, code
):
    with init_test_db(tmp_path) as db_path:
        item = 875
        _seed_item(db_path, item)
        req = _seed_requirement(
            db_path,
            item,
            "browser-inspection",
            {
                "color_scheme": "dark",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True},
                ],
            },
        )
        with ExitStack() as stack:
            for patch in _patch_external_deps(db_path):
                if patch.attribute != "open_owned_page":
                    stack.enter_context(patch)
            stack.enter_context(
                mock.patch.object(browser_qa, "open_owned_page", return_value="owned")
            )
            stack.enter_context(
                mock.patch.object(
                    browser_qa,
                    "_execute_step",
                    return_value={
                        "success": True,
                        "color_scheme": evidence,
                    },
                )
            )
            result = browser_qa.execute_scenario(
                item_id=item,
                requirement_id=req,
                project="testproj",
                base_url="http://localhost:9999",
            )
        assert result.runs[0].execution_status == "capture_failed"
        assert code in result.runs[0].errors
        conn = connect_test_db(db_path)
        assert conn.execute("SELECT COUNT(*) FROM qa_artifacts").fetchone()[0] == 0
        raw = json.loads(conn.execute("SELECT raw_result FROM qa_runs").fetchone()[0])
        conn.close()
        assert raw["color_scheme"]["requested"] == "dark"
        assert raw["color_scheme"]["observed"] == (evidence or {}).get("observed")


def test_omission_has_no_declared_requirement():
    assert case_color_scheme({}) is None
    assert color_scheme_failure(None, None) == ""


def test_invalid_stored_scheme_refuses_before_opening_or_steps(tmp_path):
    with init_test_db(tmp_path) as db_path:
        item = 877
        _seed_item(db_path, item)
        req = _seed_requirement(
            db_path,
            item,
            "browser-check",
            {
                "color_scheme": "sepia",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "assert", "target": "h1", "check": "visible"},
                ],
            },
        )
        opened = []
        with ExitStack() as stack:
            for patch in _patch_external_deps(db_path, opened_pages=opened):
                stack.enter_context(patch)
            executed = stack.enter_context(
                mock.patch.object(browser_qa, "_execute_step")
            )
            result = browser_qa.execute_scenario(
                item_id=item,
                requirement_id=req,
                project="testproj",
                base_url="http://localhost:9999",
            )
        assert result.runs[0].verdict == "error"
        assert "case_color_scheme_invalid" in result.runs[0].errors
        assert opened == []
        executed.assert_not_called()
