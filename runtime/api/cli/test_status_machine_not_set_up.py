"""`yoke status` on a machine with no setup names `yoke setup` and the folder honestly."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import status as status_module, status_render


def _status(tmp_path: Path, folder: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir()
    return status_module.build_status(
        config_path=home / ".yoke" / "config.json",
        repo_root=folder,
        check_reachability=False,
    )


def test_missing_config_reports_only_machine_not_set_up(tmp_path: Path) -> None:
    folder = tmp_path / "plain-folder"
    folder.mkdir()

    report = _status(tmp_path, folder)
    text = status_render.render_human(report)

    assert [issue["code"] for issue in report["issues"]] == ["machine_not_set_up"]
    assert "yoke setup" in report["issues"][0]["hint"]
    assert report["ok"] is False
    for wrong_hint in ("yoke config", "yoke env", "yoke project register"):
        assert wrong_hint not in text
    assert f"  folder: {folder} (not a git checkout)\n" in text
    assert "checkout:" not in text


def test_git_folder_is_labelled_checkout(tmp_path: Path) -> None:
    folder = tmp_path / "repo"
    (folder / ".git").mkdir(parents=True)

    text = status_render.render_human(_status(tmp_path, folder))

    assert f"  checkout: {folder}\n" in text
    assert "folder:" not in text


def test_engine_status_reports_only_machine_not_set_up(tmp_path: Path) -> None:
    from yoke_core.domain import machine_config_status

    home = tmp_path / "home"
    home.mkdir()
    folder = tmp_path / "plain-folder"
    folder.mkdir()

    report = machine_config_status.build_status(
        config_path=home / ".yoke" / "config.json",
        repo_root=folder,
        check_reachability=False,
    )
    text = machine_config_status.render_human(report)

    assert [issue["code"] for issue in report["issues"]] == ["machine_not_set_up"]
    for wrong_hint in ("yoke config", "yoke env", "yoke project register"):
        assert wrong_hint not in text
    assert f"  folder: {folder} (not a git checkout)\n" in text


def test_installer_written_config_is_not_setup(tmp_path: Path) -> None:
    """The public installer writes machine id and distribution only; that is not setup."""
    import json

    home = tmp_path / "home"
    (home / ".yoke").mkdir(parents=True)
    config = home / ".yoke" / "config.json"
    config.write_text(
        json.dumps(
            {
                "machine_id": "444a6196-0000-4000-8000-000000000000",
                "schema_version": 1,
                "settings": {
                    "distribution": {
                        "origin": "https://api.upyoke.com",
                        "channel": "stable",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    folder = tmp_path / "plain-folder"
    folder.mkdir()

    report = status_module.build_status(
        config_path=config, repo_root=folder, check_reachability=False
    )
    text = status_render.render_human(report)

    assert [issue["code"] for issue in report["issues"]] == ["machine_not_set_up"]
    for wrong_hint in ("yoke config", "yoke env", "yoke project register"):
        assert wrong_hint not in text
