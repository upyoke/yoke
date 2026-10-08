"""Install readiness requires the origin/channel to be durably recorded."""

import io
import subprocess

import pytest

from public_installer_helpers import (
    PUBLISHED_RELEASE_RECORD,
    RecordingRunner,
    branded_installer_glyphs as branded_installer_glyphs,
    load_installer,
)
from yoke_cli.commands.adapters.distribution import distribution_set
from yoke_cli.config import distribution


def _installer(*, runner, dry_run=False):
    module = load_installer()
    options = module.InstallOptions(
        channel="preview",
        version="1.2.3",
        yes=True,
        dry_run=dry_run,
        base_url="https://fork.example",
        no_setup=True,
    )
    instance = module.Installer(
        options,
        runner=runner,
        stdout=io.StringIO(),
        which=lambda _: "/bin/yoke",
    )
    return module, instance


def _capture_distribution(runner):
    """Isolate uv setup while retaining real distribution registration."""

    def run(argv):
        if list(argv) == ["uv", "tool", "update-shell"]:
            return subprocess.CompletedProcess(argv, 0, "shell configured", "")
        return runner(argv)

    return run


def test_install_records_actual_selection_before_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "config.json"))
    runner = RecordingRunner()
    _, instance = _installer(runner=runner)
    monkeypatch.setattr(instance, "_run_uv_install", lambda _: False)
    monkeypatch.setattr(instance, "_resolve_installed_yoke_bin", lambda: "/bin/yoke")
    monkeypatch.setattr(instance, "_smoke_yoke", lambda _: "1.2.3")
    monkeypatch.setattr(instance, "_product_boundary_audit", lambda **_: None)

    def record(argv):
        assert "is ready" not in instance.stdout.getvalue()
        assert argv[:4] == ["/bin/yoke", "config", "distribution", "set"]
        rc = distribution_set(argv[4:])
        return subprocess.CompletedProcess(argv, rc, "", "")

    monkeypatch.setattr(instance, "_repair_credential_helper", lambda _: None)
    instance.capture_runner = _capture_distribution(record)
    instance.run()
    assert distribution.recorded() == {
        "origin": "https://fork.example",
        "channel": "preview",
    }
    assert "is ready" in instance.stdout.getvalue()


def test_record_failure_prevents_ready(monkeypatch):
    runner = RecordingRunner(rc=1, stderr="disk full")
    module, instance = _installer(runner=runner)
    monkeypatch.setattr(instance, "_run_uv_install", lambda _: False)
    monkeypatch.setattr(instance, "_resolve_installed_yoke_bin", lambda: "/bin/yoke")
    monkeypatch.setattr(instance, "_smoke_yoke", lambda _: "1.2.3")
    monkeypatch.setattr(instance, "_product_boundary_audit", lambda **_: None)
    monkeypatch.setattr(instance, "_repair_credential_helper", lambda _: None)
    instance.capture_runner = _capture_distribution(runner)
    with pytest.raises(
        module.InstallError, match="distribution_record_failed"
    ) as raised:
        instance.run()
    assert "disk full" in str(raised.value)
    assert "is ready" not in instance.stdout.getvalue()


def test_dry_run_never_records_distribution(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(path))
    runner = RecordingRunner()
    _, instance = _installer(runner=runner, dry_run=True)
    instance.fetcher = lambda _url: PUBLISHED_RELEASE_RECORD
    instance.run()
    assert runner.commands == []
    assert not path.exists()
