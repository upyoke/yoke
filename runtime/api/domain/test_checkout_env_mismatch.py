"""A checkout mapped only under another env is named, not called unconfigured.

Project ids are per universe, so the checkout→project mapping is recorded
per connection env and deliberately does not resolve across universes.
These cover the diagnostic that turns that correct refusal from "no
configured project id" into the two envs involved and the supported ways
forward — without ever resolving a project id across universes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import machine_config, machine_config_writer
from yoke_contracts.machine_config import checkout_env_mismatch


@pytest.fixture()
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated machine config with a ``local`` and an ``upyoke`` env."""
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    cfg = home / "config.json"
    for env in ("local", "upyoke"):
        dsn = tmp_path / f"{env}.dsn"
        dsn.write_text(f"postgresql://localhost/{env}\n", encoding="utf-8")
        machine_config_writer.set_connection(
            env, transport="local-postgres", dsn_file=str(dsn), path=cfg,
        )
    machine_config_writer.set_active_env("local", path=cfg)
    return cfg


@pytest.fixture()
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "mini"
    root.mkdir()
    return root


def test_mapping_from_another_env_names_both_envs_and_both_recoveries(
    machine: Path, checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine_config_writer.register_project(checkout, 4, path=machine)
    monkeypatch.setenv("YOKE_ENV", "upyoke")

    assert machine_config.project_id(checkout, machine) is None
    note = checkout_env_mismatch.mismatch_note(checkout, config_path=machine)

    assert note is not None
    assert "project 4 on env local" in note
    assert "the selected env is upyoke" in note
    assert "`yoke env use local`" in note
    assert "YOKE_ENV=local" in note
    assert f"`yoke project register {checkout} --project-id N`" in note


def test_unmapped_checkout_has_no_note_so_setup_wording_stays_accurate(
    machine: Path, checkout: Path,
) -> None:
    assert checkout_env_mismatch.mismatch_note(checkout, config_path=machine) is None


def test_mapping_for_the_selected_env_resolves_and_has_no_note(
    machine: Path, checkout: Path,
) -> None:
    machine_config_writer.register_project(checkout, 4, path=machine)

    assert machine_config.project_id(checkout, machine) == 4
    assert checkout_env_mismatch.mismatch_note(checkout, config_path=machine) is None


def test_explicit_env_override_selects_which_env_is_the_mismatch(
    machine: Path, checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``YOKE_ENV`` is the selected env, so it decides both sides of the note."""
    monkeypatch.setenv("YOKE_ENV", "upyoke")
    machine_config_writer.register_project(checkout, 9, path=machine)
    monkeypatch.delenv("YOKE_ENV", raising=False)

    assert machine_config.project_id(checkout, machine) is None
    note = checkout_env_mismatch.mismatch_note(checkout, config_path=machine)

    assert note is not None
    assert "project 9 on env upyoke" in note
    assert "the selected env is local" in note

    monkeypatch.setenv("YOKE_ENV", "upyoke")
    assert machine_config.project_id(checkout, machine) == 9
    assert checkout_env_mismatch.mismatch_note(checkout, config_path=machine) is None


def test_a_second_checkout_is_never_borrowed_for_this_one(
    machine: Path, checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    machine_config_writer.register_project(other, 4, path=machine)
    monkeypatch.setenv("YOKE_ENV", "upyoke")

    assert checkout_env_mismatch.mismatch_note(checkout, config_path=machine) is None


def test_an_unreadable_config_degrades_to_no_note_instead_of_raising(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.delenv("YOKE_ENV", raising=False)

    assert checkout_env_mismatch.mismatch_note(checkout, config_path=broken) is None
