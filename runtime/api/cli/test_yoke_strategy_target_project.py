"""Unit coverage for ``yoke_cli.commands.adapters.strategy_target_project``.

target_root resolution for strategy renders/writes previously ignored
the selected project entirely (arg/env/cwd only), so a render for one
project could silently land inside a different project's checkout.
These tests isolate machine config per test and exercise the resolver
directly, independent of any CLI wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.commands.adapters import strategy_target_project as stp


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)


def _register(checkout: Path, project_id: int, *, create: bool = True) -> None:
    from yoke_cli.config import machine_config

    if create:
        checkout.mkdir(parents=True, exist_ok=True)
    payload = machine_config.load_config()
    payload.setdefault("projects", [])
    payload["projects"].append({"checkout": str(checkout), "project_id": project_id})
    config_path = machine_config.config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    config_path.write_text(json.dumps(payload), encoding="utf-8")


class TestTargetRootWasExplicit:
    def test_true_for_arg_value(self) -> None:
        assert stp.target_root_was_explicit("/tmp/x") is True

    def test_true_for_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOKE_RENDER_TARGET_ROOT", "/tmp/y")
        assert stp.target_root_was_explicit(None) is True

    def test_false_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOKE_RENDER_TARGET_ROOT", raising=False)
        assert stp.target_root_was_explicit(None) is False


class TestMappedCheckoutForProject:
    def test_returns_none_when_unregistered(self) -> None:
        assert stp.mapped_checkout_for_project(999) is None

    def test_returns_registered_checkout(self, tmp_path: Path) -> None:
        checkout = tmp_path / "platform-checkout"
        _register(checkout, 7)
        assert stp.mapped_checkout_for_project(7) == checkout

    def test_ignores_nonexistent_registered_directory(self, tmp_path: Path) -> None:
        checkout = tmp_path / "never-created"
        _register(checkout, 7, create=False)
        assert stp.mapped_checkout_for_project(7) is None


class TestRejectTargetRootProjectMismatch:
    def test_unregistered_destination_is_left_alone(self, tmp_path: Path) -> None:
        stp.reject_target_root_project_mismatch(
            tmp_path,
            project_id=1,
            project_slug="yoke",
        )  # no raise

    def test_same_project_destination_is_left_alone(self, tmp_path: Path) -> None:
        _register(tmp_path, 1)
        stp.reject_target_root_project_mismatch(
            tmp_path,
            project_id=1,
            project_slug="yoke",
        )  # no raise

    def test_other_project_destination_refuses(self, tmp_path: Path) -> None:
        checkout = tmp_path / "yoke-checkout"
        _register(checkout, 1)
        with pytest.raises(stp.StrategyTargetRootMismatchError) as exc:
            stp.reject_target_root_project_mismatch(
                checkout,
                project_id=2,
                project_slug="platform",
            )
        message = str(exc.value)
        assert "project 1" in message
        assert "platform" in message
        assert "project register" in message


class TestResolveImplicitTargetRoot:
    def test_prefers_mapped_checkout_over_fallback(self, tmp_path: Path) -> None:
        mapped = tmp_path / "platform-checkout"
        _register(mapped, 2)
        fallback = tmp_path / "yoke-checkout"
        fallback.mkdir()
        resolved = stp.resolve_implicit_target_root(
            fallback,
            project_id=2,
            project_slug="platform",
        )
        assert resolved == mapped

    def test_falls_back_when_project_unregistered(self, tmp_path: Path) -> None:
        fallback = tmp_path / "yoke-checkout"
        fallback.mkdir()
        resolved = stp.resolve_implicit_target_root(
            fallback,
            project_id=1,
            project_slug="yoke",
        )
        assert resolved == fallback

    def test_refuses_fallback_registered_to_another_project(
        self,
        tmp_path: Path,
    ) -> None:
        fallback = tmp_path / "yoke-checkout"
        _register(fallback, 1)
        with pytest.raises(stp.StrategyTargetRootMismatchError):
            stp.resolve_implicit_target_root(
                fallback,
                project_id=2,
                project_slug="platform",
            )


class TestResolveAndValidateTargetRoot:
    def test_missing_project_identity_leaves_target_root_unchanged(
        self,
        tmp_path: Path,
    ) -> None:
        resolved = stp.resolve_and_validate_target_root(
            tmp_path,
            explicit=True,
            project_id=None,
            project_slug=None,
        )
        assert resolved == tmp_path

    def test_explicit_destination_validated_in_place(self, tmp_path: Path) -> None:
        resolved = stp.resolve_and_validate_target_root(
            tmp_path,
            explicit=True,
            project_id=1,
            project_slug="yoke",
        )
        assert resolved == tmp_path

    def test_explicit_mismatch_raises(self, tmp_path: Path) -> None:
        checkout = tmp_path / "yoke-checkout"
        _register(checkout, 1)
        with pytest.raises(stp.StrategyTargetRootMismatchError):
            stp.resolve_and_validate_target_root(
                checkout,
                explicit=True,
                project_id=2,
                project_slug="platform",
            )

    def test_implicit_prefers_mapped_checkout(self, tmp_path: Path) -> None:
        mapped = tmp_path / "platform-checkout"
        _register(mapped, 2)
        fallback = tmp_path / "yoke-checkout"
        fallback.mkdir()
        resolved = stp.resolve_and_validate_target_root(
            fallback,
            explicit=False,
            project_id=2,
            project_slug="platform",
        )
        assert resolved == mapped
