"""Google's account chooser is a setup error unless the recorded account is selected."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.domain.test_browser_qa_auth_wall import _raw_result
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_core.domain.browser_qa_sign_in_evidence import (
    BROWSER_SIGN_IN_SETUP,
    PROFILE_AUTHORIZED,
    current_google_account,
    describe_sign_in,
)


def _authorized(identity: str = "default") -> dict:
    return {
        "project": "testproj",
        "identity": identity,
        "profile": PROFILE_AUTHORIZED,
        "authenticated": False,
    }


def test_chooser_without_a_match_is_a_setup_error(tmp_path: Path) -> None:
    shot = tmp_path / "chooser.png"
    shot.write_bytes(b"PNG")
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 820)
        req_id = _seed_requirement(
            db_path,
            820,
            "browser-check",
            {
                "base_url": "https://app.example.test",
                "steps": _browser_check_steps(),
            },
        )
        with patch(
            "yoke_core.domain.browser_qa_scenario.describe_sign_in",
            return_value=_authorized(),
        ):
            result = _run_scenario(
                db_path,
                820,
                requirement_id=req_id,
                base_url="https://app.example.test",
                execute_step_responses=[
                    {
                        "success": False,
                        "signInPage": True,
                        "error": (
                            "browser_sign_in_setup: Google's account chooser "
                            "does not offer buyer@example.com"
                        ),
                    },
                    {"success": True, "artifacts": [str(shot)], "signInPage": True},
                ],
            )
        assert result.verdict == "error"
        assert result.note == BROWSER_SIGN_IN_SETUP
        run = result.runs[0]
        assert run.verdict == "error"
        assert "buyer@example.com" in run.errors
        assert (
            "yoke browser authorize --project testproj --identity default"
            in run.errors
        )
        assert "Never enter credentials" in run.errors
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"]["authenticated"] is False


def test_lingering_sign_in_page_never_reports_authenticated(tmp_path: Path) -> None:
    shot = tmp_path / "signin.png"
    shot.write_bytes(b"PNG")
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 821)
        req_id = _seed_requirement(
            db_path,
            821,
            "browser-check",
            {
                "base_url": "https://app.example.test",
                "steps": _browser_check_steps(
                    {"action": "screenshot", "capture": True, "label": "signin"},
                ),
            },
        )
        with patch(
            "yoke_core.domain.browser_qa_scenario.describe_sign_in",
            return_value=_authorized(),
        ):
            result = _run_scenario(
                db_path,
                821,
                requirement_id=req_id,
                execute_step_responses=[
                    {"success": True, "signInPage": True},
                    {
                        "success": True,
                        "artifacts": [str(shot)],
                        "signInPage": True,
                    },
                ],
            )
        assert result.verdict == "pass"
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"]["profile"] == PROFILE_AUTHORIZED
        assert payload["sign_in"]["authenticated"] is False


def test_recorded_google_account_is_handed_to_the_daemon(tmp_path: Path) -> None:
    declared = parse_identity_declarations(
        {
            "identities": {
                "buyer": {
                    "sites": [
                        {
                            "site": "google",
                            "origin": "https://accounts.google.com",
                            "account": "buyer@example.com",
                            "probe": {
                                "url": "https://myaccount.google.com/",
                                "signed_in_selector": "#me",
                            },
                        },
                        {
                            "site": "shop",
                            "origin": "https://shop.example.test",
                            "account": "shop@example.com",
                            "probe": {
                                "url": "https://shop.example.test/me",
                                "signed_in_status": 200,
                            },
                        },
                    ]
                }
            }
        }
    )
    profile = tmp_path / "profile"
    profile.mkdir()
    with patch(
        "yoke_cli.config.browser_profile.resolve_authorized_profile",
        return_value=(profile, "authorized"),
    ):
        described = describe_sign_in("demo", "buyer", declared["buyer"])
    assert described["authenticated"] is False
    assert described["profile"] == PROFILE_AUTHORIZED
    assert current_google_account() == "buyer@example.com"
