"""Apply coverage for checkout-backed Yoke source activation."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import dev_setup
from yoke_cli.config import onboard_source_edit
from yoke_cli.config import project_onboard_apply
from yoke_cli.config import source_checkout_activation as activation


def _yoke_source_checkout(root: Path) -> Path:
    (root / "runtime" / "harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    return root


def _stub_activation(monkeypatch, tmp_path: Path) -> list[Path]:
    activated: list[Path] = []
    monkeypatch.setattr(
        onboard_source_edit.dev_setup,
        "install_source_checkout",
        lambda root, **_kwargs: (
            activated.append(Path(root)) or {"strategy": "source-link"}
        ),
    )
    monkeypatch.setattr(
        onboard_source_edit,
        "record_pending_dev_install",
        lambda root, config: None,
    )
    return activated


def test_existing_checkout_activates_local_client(monkeypatch, tmp_path: Path) -> None:
    root = _yoke_source_checkout(tmp_path / "my-yoke")
    activated = _stub_activation(monkeypatch, tmp_path)
    report = onboard_source_edit.build_report(
        checkout=str(root),
        remote_url=None,
        destination="local",
        same_host_self_host=False,
        self_host_directory=None,
        config_path=str(tmp_path / "config.json"),
        apply=True,
    )
    assert activated == [root]
    assert report["applied"] is True
    assert report["server_effect"] == "in-process local engine uses checkout"


def test_remote_destination_keeps_deployed_server_build(
    monkeypatch, tmp_path: Path
) -> None:
    root = _yoke_source_checkout(tmp_path / "my-yoke")
    _stub_activation(monkeypatch, tmp_path)
    report = onboard_source_edit.build_report(
        checkout=str(root),
        remote_url=None,
        destination="hosted",
        same_host_self_host=False,
        self_host_directory=None,
        config_path=str(tmp_path / "config.json"),
        apply=False,
    )
    assert report["server_effect"] == "remote server stays on its deployed build"
    assert [step["action"] for step in report["steps"]] == ["activate-yoke-source"]


def test_clone_uses_user_repository_before_activation(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "fork"
    seen: dict[str, str] = {}

    def clone(parent, name, remote_url):
        seen.update(parent=str(parent), name=name, remote_url=remote_url)
        _yoke_source_checkout(parent / name)

    monkeypatch.setattr(
        onboard_source_edit.project_clone_support,
        "clone_with_connected_access",
        clone,
    )
    activated = _stub_activation(monkeypatch, tmp_path)
    report = onboard_source_edit.build_report(
        checkout=str(root),
        remote_url="https://github.com/example/my-yoke.git",
        destination="server",
        same_host_self_host=False,
        self_host_directory=None,
        config_path=str(tmp_path / "config.json"),
        apply=True,
    )
    assert seen["remote_url"] == "https://github.com/example/my-yoke.git"
    assert activated == [root]
    assert report["applied"] is True


def test_same_host_self_host_stops_bundle_then_builds_checkout_server(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _yoke_source_checkout(tmp_path / "my-yoke")
    _stub_activation(monkeypatch, tmp_path)
    stopped: list[str | None] = []
    started: list[dict] = []
    monkeypatch.setattr(
        onboard_source_edit,
        "_stop_guided_bundle",
        lambda directory: stopped.append(directory),
    )

    class _Launcher:
        def start(self, **kwargs):
            started.append(kwargs)
            return {"ok": True, "status": "running"}

    monkeypatch.setattr(onboard_source_edit, "LocalCoreLauncher", _Launcher)
    report = onboard_source_edit.build_report(
        checkout=str(root),
        remote_url=None,
        destination="server",
        same_host_self_host=True,
        self_host_directory=str(tmp_path / "self-host"),
        config_path=str(tmp_path / "config.json"),
        apply=True,
    )
    assert stopped == [str(tmp_path / "self-host")]
    assert started == [
        {
            "from_checkout": str(root),
            "build": True,
            "config_path": str(tmp_path / "config.json"),
        }
    ]
    assert report["server_effect"] == "checkout-built server on this machine"


def test_non_yoke_checkout_refuses_with_recovery(tmp_path: Path) -> None:
    root = tmp_path / "not-yoke"
    root.mkdir()
    with pytest.raises(
        onboard_source_edit.SourceEditError, match="Choose a checkout or clone"
    ):
        onboard_source_edit.build_report(
            checkout=str(root),
            remote_url=None,
            destination="local",
            same_host_self_host=False,
            self_host_directory=None,
            config_path=str(tmp_path / "config.json"),
            apply=True,
        )


def test_pending_editable_install_marker_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    assert project_onboard_apply.pop_pending_dev_install(config) is None
    project_onboard_apply.record_pending_dev_install(tmp_path / "checkout", config)
    assert project_onboard_apply.pop_pending_dev_install(config) == str(
        tmp_path / "checkout"
    )
    assert project_onboard_apply.pop_pending_dev_install(config) is None


def test_install_source_checkout_can_skip_editable(tmp_path: Path, monkeypatch) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    monkeypatch.setattr(
        activation,
        "_run_editable_install",
        lambda _root: (_ for _ in ()).throw(AssertionError("must be deferred")),
    )
    monkeypatch.setattr(
        activation,
        "_run_source_link_subprocess",
        lambda _root, **_kwargs: {"warnings": []},
    )
    result = dev_setup.install_source_checkout(root, editable_install=False)
    assert "editable_install" not in result


def test_source_link_subprocess_puts_checkout_on_pythonpath(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _yoke_source_checkout(tmp_path / "yoke")
    captured: dict = {}

    class _Ok:
        returncode = 0
        stdout = '{"mode": "source-link", "warnings": []}'
        stderr = ""

    monkeypatch.setattr(
        activation.subprocess,
        "run",
        lambda command, **kwargs: captured.update(env=kwargs.get("env")) or _Ok(),
    )
    activation._run_source_link_subprocess(root)
    pythonpath = captured["env"]["PYTHONPATH"]
    assert str(root / "packages" / "yoke-core" / "src") in pythonpath
    assert str(root) in pythonpath
