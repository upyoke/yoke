"""Setup rejects release skew before a project-layer write."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.config import project_onboard_apply
from yoke_cli.project_install import runner, validate
from yoke_cli.project_install.files import ProjectInstallError


def test_setup_refuses_mismatched_bundle_before_writing_layer(monkeypatch, tmp_path):
    running = "0.2.0.202611201926"
    served = "0.2.0.202611202031"
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    monkeypatch.setattr(validate, "local_handshake_version", lambda: running)
    monkeypatch.setattr(project_onboard_apply.machine_config, "project_id", lambda *_: 42)
    monkeypatch.setattr(
        runner, "_resolve_bundle",
        lambda *_args, **_kwargs: ({"yoke_version": served}, "https://test.invalid"),
    )
    monkeypatch.setattr(
        runner, "assert_install_repository",
        lambda *_args, **_kwargs: pytest.fail("setup advanced past the bundle preflight"),
    )

    with pytest.raises(ProjectInstallError, match="setup_bundle_version_mismatch") as exc:
        project_onboard_apply.finish_after_dispatch(
            operation="onboard", root=tmp_path,
            result={"project": {"id": 42}},
            github_adoption={}, config_path=None, progress=None,
            github_auth_target="", scaffold_action="project-install-scaffold",
            reuse_github_auth=True,
        )

    assert running in str(exc.value)
    assert f"yoke update --version {served}" in str(exc.value)
    assert "resume this setup run" in str(exc.value)
    assert not (tmp_path / ".yoke").exists()
