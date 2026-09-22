"""Browser QA records sign-in evidence and classifies authentication walls."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _placeholder,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)
from yoke_core.domain.browser_qa_sign_in_evidence import (
    AUTHENTICATION_WALL_LABEL,
    PROFILE_AUTHORIZED,
    PROFILE_THROWAWAY,
    describe_sign_in,
)


def _raw_result(db_path: str, req_id: int) -> dict:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id = {p}",
        (req_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    return json.loads(row[0])


def _artifact_labels(db_path: str) -> list[str]:
    conn = connect_test_db(db_path)
    rows = conn.execute("SELECT metadata FROM qa_artifacts").fetchall()
    conn.close()
    labels = []
    for (raw,) in rows:
        meta = json.loads(raw)
        if meta.get("label"):
            labels.append(meta["label"])
    return labels


def test_wait_for_timeout_on_authentication_wall_is_unauthorized(
    tmp_path: Path,
) -> None:
    shot = tmp_path / "wall.png"
    shot.write_bytes(b"PNG")
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 810)
        req_id = _seed_requirement(
            db_path, 810, "browser-check",
            {
                "base_url": "https://app.example.test",
                "steps": _browser_check_steps(
                    {"action": "wait_for", "target": ".shipping-run-grid"},
                ),
            },
        )
        result = _run_scenario(
            db_path, 810, requirement_id=req_id,
            base_url="https://app.example.test",
            execute_step_responses=[
                {"success": True, "authenticationWall": True},
                {
                    "success": False,
                    "error": "Timeout 15000ms exceeded.",
                    "authenticationWall": True,
                },
                {"success": True, "artifacts": [str(shot)]},
            ],
        )
        run = result.runs[0]
        assert result.verdict == "error"
        assert result.note == EXECUTION_TARGET_UNAUTHORIZED
        assert run.verdict == "error"
        assert run.execution_status == "captured"
        assert EXECUTION_TARGET_UNAUTHORIZED in run.errors
        assert "yoke browser authorize --project testproj" in run.errors
        assert "https://app.example.test" in run.errors
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"] == {
            "profile": PROFILE_THROWAWAY,
            "authenticated": False,
        }
        assert AUTHENTICATION_WALL_LABEL in _artifact_labels(db_path)


def test_wait_for_timeout_without_wall_stays_capture_failed(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 811)
        req_id = _seed_requirement(
            db_path, 811, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": _browser_check_steps(
                    {"action": "wait_for", "target": ".missing"},
                ),
            },
        )
        result = _run_scenario(
            db_path, 811, requirement_id=req_id,
            execute_step_responses=[
                {"success": True},
                {"success": False, "error": "Timeout 200ms exceeded."},
            ],
        )
        run = result.runs[0]
        assert result.verdict == "fail"
        assert run.verdict == "fail"
        assert run.execution_status == "capture_failed"
        assert EXECUTION_TARGET_UNAUTHORIZED not in run.errors
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"]["profile"] == PROFILE_THROWAWAY
        assert payload["sign_in"]["authenticated"] is False


def test_authorized_profile_without_wall_records_authenticated(
    tmp_path: Path,
) -> None:
    shot = tmp_path / "home.png"
    shot.write_bytes(b"PNG")
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 812)
        req_id = _seed_requirement(
            db_path, 812, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": _browser_check_steps(
                    {"action": "screenshot", "capture": True, "label": "home"},
                ),
            },
        )
        with patch(
            "yoke_core.domain.browser_qa_scenario.describe_sign_in",
            return_value={
                "profile": PROFILE_AUTHORIZED,
                "authenticated": True,
            },
        ):
            result = _run_scenario(
                db_path, 812, requirement_id=req_id,
                execute_step_responses=[
                    {"success": True},
                    {"success": True, "artifacts": [str(shot)]},
                ],
            )
        assert result.verdict == "pass"
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"] == {
            "profile": PROFILE_AUTHORIZED,
            "authenticated": True,
        }
        assert result.runs[0].sign_in == payload["sign_in"]


def test_sign_in_visible_on_passing_login_case_is_not_a_failure(
    tmp_path: Path,
) -> None:
    shot = tmp_path / "login.png"
    shot.write_bytes(b"PNG")
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 813)
        req_id = _seed_requirement(
            db_path, 813, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": _browser_check_steps(
                    {"action": "wait_for", "target": ".login-form"},
                    {"action": "screenshot", "capture": True, "label": "login"},
                ),
            },
        )
        result = _run_scenario(
            db_path, 813, requirement_id=req_id,
            execute_step_responses=[
                {"success": True, "authenticationWall": True},
                {"success": True, "authenticationWall": True},
                {
                    "success": True,
                    "artifacts": [str(shot)],
                    "authenticationWall": True,
                },
            ],
        )
        assert result.verdict == "pass"
        payload = _raw_result(db_path, req_id)
        assert payload["sign_in"]["authenticated"] is False
        assert AUTHENTICATION_WALL_LABEL in _artifact_labels(db_path)


def test_describe_sign_in_authorized_when_profile_directory_exists(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    with patch(
        "yoke_cli.config.browser_profile.resolve_authorized_profile",
        return_value=(profile, "authorized"),
    ):
        assert describe_sign_in("demo") == {
            "profile": PROFILE_AUTHORIZED,
            "authenticated": True,
        }


def test_describe_sign_in_throwaway_without_profile() -> None:
    with patch(
        "yoke_cli.config.browser_profile.resolve_authorized_profile",
        return_value=(None, "no profile"),
    ):
        assert describe_sign_in("demo") == {
            "profile": PROFILE_THROWAWAY,
            "authenticated": False,
        }
