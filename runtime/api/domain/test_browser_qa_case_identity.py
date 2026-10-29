"""Named sign-in profiles are validated without refusing anonymous cases."""

import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _patch_external_deps,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    case_browser_identity,
    parse_identity_declarations,
)
from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_sign_in_evidence import resolve_case_identities


def _declared():
    site = {
        "site": "app",
        "origin": "https://app.example.test",
        "account": "account@example.test",
        "probe": {
            "url": "https://app.example.test/me",
            "signed_in_status": 200,
        },
    }
    return parse_identity_declarations(
        {"identities": {name: {"sites": [site]} for name in ("admin", "operator")}}
    )


def test_case_omission_is_distinct_from_an_explicit_default():
    assert case_browser_identity(None) is None
    assert case_browser_identity({"browser_identity": "default"}) == "default"


@pytest.mark.parametrize("declared", [parse_identity_declarations({}), _declared()])
def test_anonymous_case_remains_runnable_with_or_without_named_identities(declared):
    assert resolve_case_identities(declared, [{"method_config": "{}"}]) == ["default"]


def test_each_case_selects_its_own_named_or_anonymous_daemon():
    rows = [
        {"method_config": json.dumps(config)}
        for config in ({}, {"browser_identity": "admin"}, {"browser_identity": "operator"})
    ]
    assert resolve_case_identities(_declared(), rows) == ["default", "admin", "operator"]


def test_undeclared_case_identity_names_the_available_choices():
    with pytest.raises(BrowserIdentityError, match="^browser_identity_undeclared:") as exc:
        resolve_case_identities(
            _declared(), [{"method_config": '{"browser_identity":"missing"}'}]
        )
    assert "admin, default, operator" in str(exc.value)


@pytest.mark.parametrize("identity", [None, "admin", "operator", "missing"])
def test_identity_validation_precedes_browser_start_and_public_cases_execute(
    tmp_path, identity
):
    with init_test_db(tmp_path) as db_path:
        item_id = 825
        _seed_item(db_path, item_id)
        config = {"steps": _browser_check_steps()}
        if identity is not None:
            config["browser_identity"] = identity
        requirement_id = _seed_requirement(db_path, item_id, "browser-check", config)
        with patch("yoke_core.domain.browser_qa_scenario.describe_sign_in") as describe:
            describe.return_value = {
                "project": "testproj",
                "identity": identity or "default",
                "profile": "throwaway",
                "authenticated": False,
            }
            opened = []
            with ExitStack() as stack:
                for external in _patch_external_deps(
                    db_path,
                    identities=_declared(),
                    opened_pages=opened,
                    execute_step_responses=[{"success": True, "signInPage": False}],
                ):
                    stack.enter_context(external)
                daemon = stack.enter_context(
                    patch.object(browser_qa, "_ensure_daemon_running", return_value=None)
                )
                result = browser_qa.execute_scenario(
                    item_id=item_id,
                    project="testproj",
                    requirement_id=requirement_id,
                    base_url="http://localhost:9999",
                )
        if identity == "missing":
            assert result.note == "browser_identity_undeclared"
            assert result.verdict == "error"
            assert not result.runs
            assert not opened
            daemon.assert_not_called()
            describe.assert_not_called()
        else:
            assert result.verdict == "pass"
            assert len(opened) == 1
            assert daemon.call_args.kwargs["identity"] == (identity or "default")
            assert result.runs[0].sign_in["authenticated"] is False
            assert describe.call_args.args[1] == (identity or "default")
