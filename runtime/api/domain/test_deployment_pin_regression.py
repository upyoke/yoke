"""Version-pin regression guard for deployment runs."""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain.deployment_pin_regression import (
    PinRegressionError,
    assert_no_pin_regression,
    compare_pins,
    evaluate_pin_move,
    read_pin_at_ref,
)

PIN_FILE = "release-pin.txt"
SETTINGS = {
    "pin_file": PIN_FILE,
    "branch_by_environment": {"stage": "stage", "production": "main"},
}


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


class _Conn:
    """Minimal connection returning one project_capabilities row."""

    def __init__(self, settings_json: str | None) -> None:
        self._settings = settings_json

    def execute(self, _sql, _params):
        payload = self._settings

        class _Cursor:
            def fetchone(self):
                return None if payload is None else (payload,)

        return _Cursor()


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


def test_assert_raises_for_a_declared_project(tmp_path) -> None:
    import json

    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")
    conn = _Conn(json.dumps(SETTINGS))

    with pytest.raises(PinRegressionError, match="older than"):
        assert_no_pin_regression(
            conn,
            project_id=1,
            repo_path=str(repo),
            source_ref="origin/stale",
            target_env="production",
        )


def test_assert_is_a_noop_without_a_declaration(tmp_path) -> None:
    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")

    assert assert_no_pin_regression(
        _Conn(None),
        project_id=1,
        repo_path=str(repo),
        source_ref="origin/stale",
        target_env="production",
    ) is None


def test_override_bypasses_the_guard(tmp_path) -> None:
    import json

    repo = _pin_repo(tmp_path, "0.1.1+launch.145", "0.1.1+launch.144")

    assert assert_no_pin_regression(
        _Conn(json.dumps(SETTINGS)),
        project_id=1,
        repo_path=str(repo),
        source_ref="origin/stale",
        target_env="production",
        override=True,
    ) is None
