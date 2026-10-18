"""Project-mapping writer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import machine_config_writer as writer
from yoke_core.domain.machine_config_writer import MachineConfigWriteError


@pytest.fixture()
def home(tmp_path, monkeypatch):
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return machine_home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text())


def _seed_https(home: Path, tmp_path: Path, env: str = "stage") -> Path:
    token_file = tmp_path / f"{env}.token"
    token_file.write_text("tok\n")
    writer.set_connection(
        env,
        transport="https",
        api_url="https://api.example",
        token_file=str(token_file),
    )
    return token_file


def _rows(config: dict, checkout: str) -> list[dict]:
    return [
        e
        for e in config["connection_projects"][config["active_env"]]
        if e["checkout"] == checkout
    ]


def _row(config: dict, checkout: str, env: str | None = None) -> dict:
    rows = _rows(config, checkout)
    if env is not None:
        rows = [e for e in rows if e.get("env") == env]
    assert len(rows) == 1, rows
    return rows[0]


class TestRegisterProject:
    def test_registers_resolved_checkout(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = writer.register_project(repo, 7)

        entry = _row(_config(home), result["checkout"])
        assert entry["project_id"] == 7
        assert "board" not in entry

    def test_register_refuses_retired_board_flags(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(MachineConfigWriteError, match="board is retired"):
            writer.register_project(
                repo,
                7,
                board_scope="all",
                board_render_path=".yoke/BOARD-ALL.md",
            )

    def test_registration_has_distinct_selected_connection_slots(
        self, home, tmp_path, monkeypatch
    ):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        writer.register_project(repo, 7)
        monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
        writer.register_project(repo, 7)
        assert _config(home)["connection_projects"] == {
            "stage": [{"checkout": str(repo.resolve()), "project_id": 7}],
            "prod-db-admin": [{"checkout": str(repo.resolve()), "project_id": 7}],
        }

    def test_missing_directory_is_refused(self, home, tmp_path):
        _seed_https(home, tmp_path)

        with pytest.raises(MachineConfigWriteError, match="not a directory"):
            writer.register_project(tmp_path / "absent", 7)

    def test_nonpositive_project_id_is_refused(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(MachineConfigWriteError, match="positive integer"):
            writer.register_project(repo, 0)

    def test_reassigning_an_occupied_slot_is_refused_without_reassign(
        self,
        home,
        tmp_path,
    ):
        _seed_https(home, tmp_path)
        original = tmp_path / "real-checkout"
        original.mkdir()
        writer.register_project(original, 7)
        scratch = tmp_path / "scratch-clone"
        scratch.mkdir()

        with pytest.raises(MachineConfigWriteError, match="already routed to"):
            writer.register_project(scratch, 7)

        # The real checkout's routing is untouched by the refused attempt.
        entry = _row(_config(home), str(original.resolve()))
        assert entry["project_id"] == 7

    def test_reassign_true_moves_the_slot_to_the_new_checkout(
        self,
        home,
        tmp_path,
    ):
        _seed_https(home, tmp_path)
        original = tmp_path / "real-checkout"
        original.mkdir()
        writer.register_project(original, 7)
        scratch = tmp_path / "scratch-clone"
        scratch.mkdir()

        result = writer.register_project(scratch, 7, reassign=True)

        config = _config(home)
        assert _rows(config, str(original.resolve())) == []
        entry = _row(config, result["checkout"])
        assert entry["project_id"] == 7

    def test_first_time_registration_needs_no_reassign(self, home, tmp_path):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = writer.register_project(repo, 7)

        assert _row(_config(home), result["checkout"])["project_id"] == 7

    def test_reregistering_the_same_checkout_needs_no_reassign(
        self,
        home,
        tmp_path,
    ):
        _seed_https(home, tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        writer.register_project(repo, 7)

        result = writer.register_project(repo, 7)

        assert _row(_config(home), result["checkout"])["project_id"] == 7
