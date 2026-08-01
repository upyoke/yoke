"""Version-pin regression guard for deployment runs."""

from __future__ import annotations

import argparse
import json
import subprocess
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.deployment_pin_guard import pin_regression_error
from yoke_cli.commands.deployment_pin import (
    PinRegressionError,
    assert_no_pin_regression,
    compare_pins,
    evaluate_pin_move,
    read_pin_at_ref,
)
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)

PIN_FILE = "release-pin.txt"
SETTINGS = {
    "pin_file": PIN_FILE,
    "branch_by_environment": {"stage": "stage", "production": "main"},
}
GUARD = "yoke_cli.commands.adapters.deployment_pin_guard"


def _git(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _pin_repo(tmp_path, main_pin: str, feature_pin: str):
    """A repo whose main advanced past a branch that still holds an old pin."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "pin@example.test")
    _git(origin, "config", "user.name", "Pin Test")
    (origin / PIN_FILE).write_text(f"{feature_pin}\n")
    _git(origin, "add", PIN_FILE)
    _git(origin, "commit", "-qm", "pin at feature level")
    _git(origin, "branch", "stale")
    (origin / PIN_FILE).write_text(f"{main_pin}\n")
    _git(origin, "add", PIN_FILE)
    _git(origin, "commit", "-qm", "advance pin")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)],
        check=True,
        capture_output=True,
    )
    return clone


def _guard_args(repo, **overrides) -> argparse.Namespace:
    values = {
        "project": "demo",
        "flow": "demo-production",
        "target_env": None,
        "project_repo_path": str(repo),
        "source_ref": "origin/stale",
        "allow_pin_regression": False,
        "session_id": "test-session",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _stub_control_plane(settings_json: str | None):
    """Answer the guard's two reads without touching a control plane."""
    calls: list[tuple[str, dict]] = []

    def dispatcher(*, function_id, target, payload, actor):
        del target, actor
        calls.append((function_id, payload))
        if function_id == "projects.capability_settings.get":
            if settings_json is None:
                return FunctionCallResponse(
                    success=False,
                    function=function_id,
                    version="v1",
                    error=FunctionError(
                        code="not_found",
                        message="capability 'release_pin' was not found",
                    ),
                )
            return FunctionCallResponse(
                success=True,
                function=function_id,
                version="v1",
                result={"settings_json": settings_json},
            )
        if function_id == "deployment_flows.get":
            return FunctionCallResponse(
                success=True,
                function=function_id,
                version="v1",
                result={"value": "production"},
            )
        raise AssertionError(f"unexpected function id {function_id!r}")

    return dispatcher, calls


def test_compare_pins_orders_numeric_segments_numerically() -> None:
    assert compare_pins("0.1.1+launch.9", "0.1.1+launch.10") == -1
    assert compare_pins("0.1.1+launch.145", "0.1.1+launch.144") == 1
    assert compare_pins("0.1.1+launch.144", "0.1.1+launch.144") == 0


def test_read_pin_at_ref_returns_none_for_a_missing_file(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "2", "1")
    assert read_pin_at_ref(str(repo), "origin/main", "absent.txt") is None


def test_stale_ref_against_advanced_branch_is_a_regression(tmp_path) -> None:
    """The live trap: a ref captured before a pin bump rolls the pin back."""
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")

    comparison = evaluate_pin_move(
        settings=SETTINGS,
        repo_path=str(repo),
        source_ref="origin/stale",
        target_env="production",
    )

    assert comparison.regressed is True
    assert comparison.candidate == "0.1.1+launch.144"
    assert comparison.current == "0.1.1+launch.145"


def test_current_ref_is_not_a_regression(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")

    comparison = evaluate_pin_move(
        settings=SETTINGS,
        repo_path=str(repo),
        source_ref="origin/main",
        target_env="production",
    )

    assert comparison.regressed is False


def test_undeclared_environment_skips_with_a_reason(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "2", "1")

    comparison = evaluate_pin_move(
        settings=SETTINGS,
        repo_path=str(repo),
        source_ref="origin/main",
        target_env="ephemeral",
    )

    assert comparison.regressed is False
    assert "no pin branch declared" in (comparison.skipped_reason or "")


def test_assert_raises_for_a_stale_ref(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")

    with pytest.raises(PinRegressionError, match="older than"):
        assert_no_pin_regression(
            settings=SETTINGS,
            repo_path=str(repo),
            source_ref="origin/stale",
            target_env="production",
        )


def test_guard_refuses_a_declared_project_and_names_both_versions(
    tmp_path,
) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")
    dispatcher, calls = _stub_control_plane(json.dumps(SETTINGS))

    with (
        patch(f"{GUARD}.call_dispatcher", side_effect=dispatcher),
        patch(f"{GUARD}.ensure_handlers_loaded"),
    ):
        message = pin_regression_error(_guard_args(repo))

    assert message is not None
    assert "0.1.1+launch.144" in message
    assert "0.1.1+launch.145" in message
    assert "override" in message
    assert calls[0] == (
        "projects.capability_settings.get",
        {"project": "demo", "cap_type": "release_pin"},
    )
    assert calls[1] == (
        "deployment_flows.get",
        {"flow_id": "demo-production", "field": "target_env"},
    )


def test_guard_is_a_noop_without_a_declaration(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")
    dispatcher, calls = _stub_control_plane(None)

    with (
        patch(f"{GUARD}.call_dispatcher", side_effect=dispatcher),
        patch(f"{GUARD}.ensure_handlers_loaded"),
    ):
        assert pin_regression_error(_guard_args(repo)) is None

    assert [function_id for function_id, _ in calls] == [
        "projects.capability_settings.get"
    ]


def test_guard_skips_an_unreadable_pin(tmp_path) -> None:
    """A pin file absent on one side is not evidence of a rollback."""
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")
    settings = dict(SETTINGS, pin_file="absent.txt")
    dispatcher, _calls = _stub_control_plane(json.dumps(settings))

    with (
        patch(f"{GUARD}.call_dispatcher", side_effect=dispatcher),
        patch(f"{GUARD}.ensure_handlers_loaded"),
    ):
        assert pin_regression_error(_guard_args(repo)) is None


def test_override_bypasses_the_guard(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")
    dispatcher, calls = _stub_control_plane(json.dumps(SETTINGS))

    with (
        patch(f"{GUARD}.call_dispatcher", side_effect=dispatcher),
        patch(f"{GUARD}.ensure_handlers_loaded"),
    ):
        args = _guard_args(repo, allow_pin_regression=True)
        assert pin_regression_error(args) is None

    assert calls == []
