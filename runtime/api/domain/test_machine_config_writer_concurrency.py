"""Concurrency and compare-and-swap tests for machine-config writes."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import threading

import pytest

from yoke_cli.config import machine_config_file
from yoke_cli.config import writer
from yoke_contracts.machine_config import schema as contract


def _github(ref: str, *, slug: str = "yoke") -> dict:
    return {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": slug,
        "app_id": 42,
        "client_id": "Iv1.example",
        "profile_source": contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": ref,
            "status": "authorized",
        },
    }


def test_writer_waits_for_stable_lock_then_merges_latest_payload(
    tmp_path: Path,
) -> None:
    home = tmp_path / "machine-home"
    config = home / "config.json"
    repo = tmp_path / "repo"
    repo.mkdir()
    started = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []

    def register() -> None:
        started.set()
        try:
            writer.register_project(repo, 7, path=config)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            finished.set()

    seed = contract.canonical_example_payload()
    seed.update({
        "temp_root": str(tmp_path / "tmp"),
        "cache_dir": str(tmp_path / "cache"),
    })
    with machine_config_file.exclusive_lock(config):
        worker = threading.Thread(target=register)
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
        machine_config_file.atomic_write_text(
            config, json.dumps(seed, indent=2) + "\n",
        )
    assert finished.wait(2)
    worker.join(timeout=2)

    assert failures == []
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["temp_root"] == seed["temp_root"]
    assert payload["cache_dir"] == seed["cache_dir"]
    entry = contract.project_entry_for_checkout(
        payload, repo.resolve(), env=payload["active_env"],
    )
    assert entry["project_id"] == 7
    lock_path = config.with_name(config.name + ".lock")
    assert lock_path.is_file()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_every_public_writer_mutation_is_serialized() -> None:
    for name in (
        "clear_github", "register_project", "set_active_env",
        "set_connection", "set_credential", "set_github",
        "set_runtime_paths", "stamp_untagged_project_envs",
    ):
        assert hasattr(getattr(writer, name), "__wrapped__"), name


def test_github_replace_rejects_stale_credential_and_returns_actual_ref(
    tmp_path: Path,
) -> None:
    config = tmp_path / "machine-home" / "config.json"
    first_ref = str(tmp_path / "first.json")
    second_ref = str(tmp_path / "second.json")
    writer.set_github(
        _github(first_ref), expected_credential_ref="", path=config,
    )

    with pytest.raises(
        writer.MachineConfigWriteError, match="changed during this operation",
    ):
        writer.set_github(
            _github(second_ref, slug="replacement"),
            expected_credential_ref="stale-ref", path=config,
        )

    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["github"]["app_slug"] == "yoke"
    result = writer.set_github(
        _github(second_ref, slug="replacement"),
        expected_credential_ref=first_ref, path=config,
    )
    assert result["replaced_credential_ref"] == first_ref
    removed = writer.clear_github(path=config)
    assert removed["removed_credential_ref"] == second_ref
    assert not config.exists()
    assert config.with_name(config.name + ".lock").is_file()


def test_writer_refuses_symlink_config_target(tmp_path: Path) -> None:
    home = tmp_path / "machine-home"
    home.mkdir(mode=0o700)
    target = tmp_path / "outside.json"
    original = json.dumps(contract.canonical_example_payload()) + "\n"
    target.write_text(original, encoding="utf-8")
    config = home / "config.json"
    config.symlink_to(target)

    with pytest.raises(
        writer.MachineConfigWriteError, match="regular file",
    ):
        writer.set_runtime_paths(
            temp_root=tmp_path / "tmp", cache_dir=tmp_path / "cache",
            path=config,
        )

    assert config.is_symlink()
    assert target.read_text(encoding="utf-8") == original


def test_writer_refuses_symlink_lock(tmp_path: Path) -> None:
    home = tmp_path / "machine-home"
    home.mkdir(mode=0o700)
    config = home / "config.json"
    lock_target = tmp_path / "outside.lock"
    lock_target.write_text("untouched", encoding="utf-8")
    config.with_name(config.name + ".lock").symlink_to(lock_target)

    with pytest.raises(writer.MachineConfigWriteError, match="lock"):
        writer.set_runtime_paths(
            temp_root=tmp_path / "tmp", cache_dir=tmp_path / "cache",
            path=config,
        )

    assert lock_target.read_text(encoding="utf-8") == "untouched"
