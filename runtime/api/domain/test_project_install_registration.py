"""Project install validates identity and registration before writing files."""

from __future__ import annotations

import pytest

from runtime.api.cli.project_install_publication_test_support import local_only_checkout
from runtime.api.domain.project_install_test_support import MANIFEST_REL, _tree_bytes
from yoke_cli.project_install import runner as project_install
from yoke_cli.project_install.runner import ProjectInstallError
from yoke_core.domain.project_install_test_helpers import make_bundle


@pytest.fixture()
def repo(tmp_path):
    return local_only_checkout(tmp_path)


def test_bundle_identity_is_validated_before_machine_registration(
    repo,
    tmp_path,
    monkeypatch,
) -> None:
    cfg = tmp_path / "machine-home" / "config.json"
    mismatch = make_bundle()
    mismatch["project_id"] = 8
    monkeypatch.setattr(
        project_install,
        "_resolve_bundle",
        lambda *_args, **_kwargs: (mismatch, "test"),
    )
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="does not match"):
        project_install.install(repo, project_id=7, config_path=cfg)

    assert _tree_bytes(repo) == before
    assert not cfg.exists()


def test_install_requires_a_resolvable_project_id(repo, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    cfg = tmp_path / "machine-home" / "config.json"

    with pytest.raises(ProjectInstallError) as exc_info:
        project_install.install(repo, config_path=cfg)
    assert "--project-id" in str(exc_info.value)


def test_install_registers_checkout_mapping_for_explicit_id(
    repo, tmp_path, monkeypatch
) -> None:
    from yoke_core.domain import machine_config
    from yoke_cli.config import writer as machine_config_writer

    cfg = tmp_path / "machine-home" / "config.json"
    dsn = tmp_path / "local.dsn"
    dsn.write_text("postgresql://localhost/yoke\n", encoding="utf-8")
    machine_config_writer.set_connection(
        "local", transport="local-postgres", dsn_file=str(dsn), path=cfg
    )
    monkeypatch.setattr(
        project_install,
        "_resolve_bundle",
        lambda pid, **kw: (make_bundle(), "test"),
    )

    report = project_install.install(repo, project_id=7, config_path=cfg)

    assert report["machine_config_newly_registered"] is True
    assert machine_config.project_id(repo, cfg) == 7

    # Second run: mapping exists, no re-registration; id resolves from config.
    report = project_install.refresh(repo, config_path=cfg)
    assert report["operation"] == "refresh"
    assert report["machine_config_newly_registered"] is False


def test_registration_failure_leaves_repo_untouched(
    repo, tmp_path, monkeypatch
) -> None:
    from yoke_cli.config.writer import MachineConfigWriteError

    cfg = tmp_path / "machine-home" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}\n", encoding="utf-8")  # fails the writer contract
    monkeypatch.setattr(
        project_install,
        "_resolve_bundle",
        lambda pid, **kw: (make_bundle(), "test"),
    )

    with pytest.raises(MachineConfigWriteError):
        project_install.install(repo, project_id=7, config_path=cfg)

    assert not (repo / MANIFEST_REL).exists(), (
        "an unwritable machine config fails fast before any repo write"
    )
    assert not (repo / ".claude").exists()
    assert not (repo / ".yoke").exists()
