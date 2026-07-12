"""Tests for the fresh-database ``yoke self-host import`` adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands import self_host_import as command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli import product_boundary_inventory
from yoke_cli.self_host import bundle


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def import_files(tmp_path):
    directory = tmp_path / "server"
    bundle.write_bundle(directory=str(directory))
    archive = tmp_path / "universe.dump"
    archive.write_bytes(b"PGDMP test archive")
    archive.chmod(0o600)
    return directory.resolve(), archive


def _success_payload() -> dict[str, object]:
    return {
        "ok": True,
        "org": "portable",
        "actor_id": 7,
        "token_id": 11,
        "raw_token": "yoke_v1_ReplacementCredential",
        "revoked_token_count": 3,
        "revoked_web_session_count": 2,
        "archive": {"bytes": 18, "table_entries": 77},
    }


def _completed(argv, *, returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_import_runs_exact_compose_sequence_and_prints_one_time_token(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    calls = []
    responses = [
        (0, b"", b""),
        (0, b"", b""),
        (0, b"", b""),
        (0, json.dumps(_success_payload()).encode(), b""),
    ]

    def fake_run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        returncode, stdout, stderr = responses.pop(0)
        return _completed(argv, returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(command, "_SUBPROCESS_RUN", fake_run)
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 0
    output = capsys.readouterr().out
    assert "yoke_v1_ReplacementCredential" in output
    assert "shown once" in output
    assert responses == []
    assert [call[0] for call in calls] == [
        ("docker", "compose", "ps", "--all", "--format", "json", "core"),
        (
            "docker",
            "compose",
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "120",
            "db",
        ),
        ("docker", "compose", "ps", "--all", "--format", "json", "core"),
        (
            "docker",
            "compose",
            "run",
            "--rm",
            "-T",
            "core",
            "python3",
            "-m",
            "yoke_core.domain.universe_import_cli",
            "--stdin",
        ),
    ]
    assert all(call[1]["cwd"] == directory for call in calls)
    assert calls[-1][1]["stdin"].closed


def test_import_json_mode_emits_machine_readable_credential(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    responses = iter(
        [
            _completed([], stdout=b""),
            _completed([]),
            _completed([], stdout=b""),
            _completed([], stdout=json.dumps(_success_payload()).encode()),
        ]
    )
    monkeypatch.setattr(command, "_SUBPROCESS_RUN", lambda *_a, **_k: next(responses))
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["token_id"] == 11


def test_import_refuses_running_core_before_starting_database(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    calls = []

    def running(argv, **kwargs):
        calls.append(tuple(argv))
        return _completed(argv, stdout=b'[{"State":"running"}]\n')

    monkeypatch.setattr(command, "_SUBPROCESS_RUN", running)
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    assert len(calls) == 1
    assert "core service is not stopped" in capsys.readouterr().err


@pytest.mark.parametrize("state", ("paused", "restarting"))
def test_import_refuses_non_stopped_core_states(
    import_files, monkeypatch, capsys, state
):
    directory, archive = import_files
    monkeypatch.setattr(
        command,
        "_SUBPROCESS_RUN",
        lambda argv, **_kwargs: _completed(
            argv, stdout=json.dumps([{"State": state}]).encode()
        ),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    assert state in capsys.readouterr().err


def test_failed_container_never_echoes_its_stdout_secret(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    responses = iter(
        [
            _completed([], stdout=b""),
            _completed([]),
            _completed([], stdout=b""),
            _completed(
                [],
                returncode=1,
                stdout=b"yoke_v1_MustNeverEscape",
                stderr=b"destination is not catalog-empty",
            ),
        ]
    )
    monkeypatch.setattr(command, "_SUBPROCESS_RUN", lambda *_a, **_k: next(responses))
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    output = capsys.readouterr()
    assert "yoke_v1_MustNeverEscape" not in output.out + output.err
    assert "not catalog-empty" in output.err


def test_malformed_success_teaches_safe_credential_recovery(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    responses = iter(
        [
            _completed([], stdout=b""),
            _completed([]),
            _completed([], stdout=b""),
            _completed([], stdout=b"not-json yoke_v1_Hidden"),
        ]
    )
    monkeypatch.setattr(command, "_SUBPROCESS_RUN", lambda *_a, **_k: next(responses))
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    error = capsys.readouterr().err
    assert "yoke_v1_Hidden" not in error
    assert "--recover-credential" in error


def test_import_requires_owner_only_single_link_archive(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    archive.chmod(0o644)
    monkeypatch.setattr(
        command,
        "_SUBPROCESS_RUN",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("compose must not run")),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    assert "chmod 600" in capsys.readouterr().err


def test_import_refuses_bundle_with_git_tracked_secrets(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files

    def tracked(_target):
        raise bundle.protection.SelfHostProtectionError(
            "Git already tracks sensitive self-host bundle files"
        )

    monkeypatch.setattr(bundle.protection, "assert_sensitive_paths_untracked", tracked)
    monkeypatch.setattr(
        command,
        "_SUBPROCESS_RUN",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("compose must not run")),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    assert "Git already tracks" in capsys.readouterr().err


def test_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["self-host", "import", "universe.dump"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is command.self_host_import
    assert remaining == ["universe.dump"]


def test_product_boundary_classifies_import_as_product_client():
    rows = {
        row.command_helper: row
        for row in product_boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }
    assert (
        rows["yoke self-host import"].disposition
        == product_boundary_inventory.PRODUCT_CLIENT
    )
