"""Failed onboarding retains the exact checkout mapping for cleanup and retry."""

import pytest

from yoke_cli.config import machine_config, writer, project_onboard_apply
from yoke_cli.project_install.files import ProjectInstallError


@pytest.mark.parametrize("failure", ["binding", "install"])
def test_failed_setup_keeps_project_discoverable(tmp_path, monkeypatch, failure):
    config = tmp_path / "home/.yoke/config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(config.parent))
    writer.set_connection(
        "prod",
        transport="https",
        api_url="https://fixture.invalid",
        token="fixture",
        path=config,
    )
    root = tmp_path / "checkout"
    root.mkdir()

    def fail(*args, **kwargs):
        assert machine_config.project_id(root, config) == 7
        raise ProjectInstallError("fixture install refused")

    monkeypatch.setattr(
        project_onboard_apply.progress_steps,
        "store_github_binding",
        fail if failure == "binding" else lambda *a, **k: None,
    )
    monkeypatch.setattr(project_onboard_apply.install_runner, "install", fail)
    with pytest.raises(ProjectInstallError, match="fixture install refused"):
        project_onboard_apply.finish_after_dispatch(
            operation="project.create",
            root=root,
            result={"project": {"id": 7}},
            github_adoption={},
            config_path=config,
            progress=None,
            github_auth_target="project",
            scaffold_action="project-install-scaffold",
            reuse_github_auth=False,
        )

    assert machine_config.project_id(root, config) == 7
    assert not (root / ".yoke").exists()
