"""Tests for the one-file, one-consent ``yoke self-host import`` adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

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
    archive = tmp_path / "universe.tar"
    archive.write_bytes(b"portable universe tar")
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


def test_import_streams_archive_through_private_handoff(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    calls = []
    monkeypatch.setattr(
        command, "_SUBPROCESS_RUN", lambda *_a, **_k: _completed([], stdout=b"")
    )

    def stream(target, *, archive):
        calls.append((target, archive.read()))
        return json.dumps(_success_payload()).encode()

    monkeypatch.setattr(command.runtime, "import_universe", stream)
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 0
    )
    assert calls == [(directory, b"portable universe tar")]
    assert "yoke_v1_ReplacementCredential" in capsys.readouterr().out


def test_import_json_mode_emits_machine_readable_credential(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    monkeypatch.setattr(
        command, "_SUBPROCESS_RUN", lambda *_a, **_k: _completed([], stdout=b"")
    )
    monkeypatch.setattr(
        command.runtime,
        "import_universe",
        lambda *_a, **_k: json.dumps(_success_payload()).encode(),
    )
    assert (
        command.self_host_import(
            [str(archive), "--dir", str(directory), "--yes", "--json"]
        )
        == 0
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
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
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
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
    assert state in capsys.readouterr().err


def test_failed_container_never_echoes_stdout_secret(import_files, monkeypatch, capsys):
    directory, archive = import_files
    monkeypatch.setattr(
        command, "_SUBPROCESS_RUN", lambda *_a, **_k: _completed([], stdout=b"")
    )

    def refuse(*_a, **_k):
        raise command.runtime.SelfHostRuntimeError("self_host_import_handoff_failed")

    monkeypatch.setattr(command.runtime, "import_universe", refuse)
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
    assert "self_host_import_handoff_failed" in capsys.readouterr().err


def test_malformed_success_teaches_safe_recovery(import_files, monkeypatch, capsys):
    directory, archive = import_files
    monkeypatch.setattr(
        command, "_SUBPROCESS_RUN", lambda *_a, **_k: _completed([], stdout=b"")
    )
    monkeypatch.setattr(
        command.runtime, "import_universe", lambda *_a, **_k: b"not-json yoke_v1_Hidden"
    )
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
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
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
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
    assert (
        command.self_host_import([str(archive), "--dir", str(directory), "--yes"]) == 1
    )
    assert "Git already tracks" in capsys.readouterr().err


def test_import_requires_consent_when_non_interactive(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    monkeypatch.setattr(command.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(
        command,
        "_SUBPROCESS_RUN",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("compose must not run")),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    error = capsys.readouterr().err
    assert "replaces the universe" in error
    assert "--yes" in error


def test_import_prompt_collects_typed_replace_consent(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    monkeypatch.setattr(command.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _prompt: "replace")
    monkeypatch.setattr(
        command, "_SUBPROCESS_RUN", lambda *_a, **_k: _completed([], stdout=b"")
    )
    monkeypatch.setattr(
        command.runtime,
        "import_universe",
        lambda *_a, **_k: json.dumps(_success_payload()).encode(),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 0
    assert "yoke_v1_ReplacementCredential" in capsys.readouterr().out


def test_import_prompt_refusal_cancels_before_any_compose_call(
    import_files, monkeypatch, capsys
):
    directory, archive = import_files
    monkeypatch.setattr(command.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    monkeypatch.setattr(
        command,
        "_SUBPROCESS_RUN",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("compose must not run")),
    )
    assert command.self_host_import([str(archive), "--dir", str(directory)]) == 1
    assert "cancelled" in capsys.readouterr().err


def test_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["self-host", "import", "universe.tar"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is command.self_host_import
    assert remaining == ["universe.tar"]


def test_product_boundary_classifies_import_as_product_client():
    rows = {
        row.command_helper: row
        for row in product_boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }
    assert (
        rows["yoke self-host import"].disposition
        == product_boundary_inventory.PRODUCT_CLIENT
    )
