"""Refuse setup release skew before claiming checkout registration."""

from __future__ import annotations

import subprocess

import pytest

from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import project_onboard_apply, writer
from yoke_cli.project_install import validate
from yoke_contracts.project_contract.install_error import ProjectInstallError


def test_release_mismatch_leaves_registration_for_resumed_setup(monkeypatch, tmp_path):
    running = "0.2.0.202611201926"
    served = "0.2.0.202611202031"
    config = tmp_path / "home" / "config.json"
    checkout = tmp_path / "checkout"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(config.parent))
    writer.set_connection(
        "test", transport="https", api_url="https://test.invalid",
        token="fixture", path=config,
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
    scaffold = ({"yoke_version": served}, "https://test.invalid")
    monkeypatch.setattr(validate, "local_handshake_version", lambda: running)
    monkeypatch.setattr(
        project_onboard_apply, "resolve_bundle", lambda *_args, **_kwargs: scaffold,
    )
    monkeypatch.setattr(
        project_onboard_apply.install_runner, "install",
        lambda *_args, **_kwargs: pytest.fail("setup advanced past the bundle preflight"),
    )
    calls = []
    monkeypatch.setattr(
        project_onboard_apply.project_onboard_installed_layer, "remove_layer",
        lambda *_args, **_kwargs: calls.append("remove"),
    )
    monkeypatch.setattr(
        project_onboard_apply.progress_steps, "store_github_binding",
        lambda *_args, **_kwargs: calls.append("binding"),
    )

    def apply():
        return project_onboard_apply.finish_after_dispatch(
            operation="onboard", root=checkout,
            result={"project": {"id": 42}}, github_adoption={},
            config_path=config, progress=None,
            github_auth_target="", scaffold_action="project-install-scaffold",
            reuse_github_auth=False,
            remove_existing_layer=True,
        )

    with pytest.raises(ProjectInstallError, match="setup_bundle_version_mismatch") as exc:
        apply()

    assert running in str(exc.value)
    assert f"yoke update --version {served}" in str(exc.value)
    assert "resume this setup run" in str(exc.value)
    assert machine_config.project_id(checkout, config) is None
    assert not calls
    assert not (checkout / ".yoke").exists()

    def install(root, *, resolved_bundle, owns_registration, **_kwargs):
        assert root == checkout
        assert resolved_bundle is scaffold
        assert owns_registration is True
        assert machine_config.project_id(checkout, config) == 42
        calls.append("install")
        raise ProjectInstallError("scaffold started")

    running = served
    monkeypatch.setattr(project_onboard_apply.install_runner, "install", install)
    with pytest.raises(ProjectInstallError, match="scaffold started"):
        apply()

    assert calls == ["remove", "binding", "install"]
