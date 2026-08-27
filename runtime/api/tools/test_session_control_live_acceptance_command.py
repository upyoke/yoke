"""Security and delegation tests for the public live-acceptance command."""

from __future__ import annotations

import io
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from runtime.api.tools import session_control_live_acceptance_command as command
from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACES,
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    require_exact_desktop_active_policy,
)
from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
from yoke_core.domain.deploy_product_source import DeployProductSourceError


RELEASE_SHA = "a" * 40


def _versions() -> dict[str, str]:
    return {
        surface: SESSION_SURFACE_CAPABILITIES[surface].minimum_version
        for surface in ACCEPTANCE_SURFACES
    }


def _bindings() -> dict[str, object]:
    return {
        "schema": 1,
        "versions": _versions(),
        "claude_desktop_session_id": "desktop-session",
        "broker": {
            "target_session_id": "broker-target",
            "machine_id": "machine-one",
            "peer_session_id": "broker-peer",
        },
    }


def _argv(*extra: str) -> list[str]:
    return [
        "--project",
        "yoke",
        "--release-sha",
        RELEASE_SHA,
        "--run-id",
        "release-proof",
        "--bindings-stdin",
        *extra,
    ]


def _allow_source(monkeypatch) -> None:
    monkeypatch.setattr(command, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        command,
        "validate_product_source",
        lambda _cwd, _release: SimpleNamespace(commit=RELEASE_SHA),
    )
    monkeypatch.setattr(
        command,
        "resolve_or_prepare_broker_binding",
        lambda *a, **k: _ready_decision(),
    )


class _UnreadableStdin:
    def read(self, _size: int) -> str:
        raise AssertionError("stdin must not be read")


def test_matrix_builder_owns_the_exact_six_modes_roles_and_routes() -> None:
    bindings = command.LiveAcceptanceBindings.model_validate(_bindings())
    document = command.build_acceptance_matrix_document("yoke", bindings)

    assert document["schema"] == SCHEMA_VERSION
    assert document["project"] == "yoke"
    cells = document["cells"]
    assert len(cells) == 6
    assert [cell["surface"] for cell in cells[:5]] == list(ACCEPTANCE_SURFACES)
    desktop = cells[1]
    assert desktop == {
        "surface": "claude-desktop",
        "expected_version": _versions()["claude-desktop"],
        "mode": "identify",
        "acceptance_role": "surface",
        "wake_route": "direct",
        "session_id": "desktop-session",
    }
    assert all(
        cell["mode"] == "create" and cell["wake_route"] == "direct"
        for cell in (cells[0], *cells[2:5])
    )
    broker = cells[-1]
    assert broker["surface"] == command.BROKER_ACCEPTANCE_SURFACE
    assert broker["acceptance_role"] == "broker"
    assert broker["wake_route"] == "machine_selected"
    assert broker["session_id"] == "broker-target"
    assert broker["broker_session_id"] == "broker-peer"


def test_candidate_builder_refuses_when_floor_proves_every_route() -> None:
    bindings = _bindings()
    bindings["versions"]["claude-desktop"] = (
        CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION
    )

    with pytest.raises(AcceptanceContractError) as raised:
        command.build_acceptance_matrix_document(
            "yoke",
            command.LiveAcceptanceBindings.model_validate(bindings),
            qualification_candidate=True,
        )

    assert raised.value.code == "candidate_cells_empty"


def test_subagent_refuses_before_source_validation_or_stdin(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(command, "is_subagent_execution", lambda: True)
    monkeypatch.setattr(
        command,
        "validate_product_source",
        lambda *_args: (_ for _ in ()).throw(AssertionError("source inspected")),
    )
    monkeypatch.setattr(command.sys, "stdin", _UnreadableStdin())

    assert command.main(_argv("--preview")) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == (
        "top_level_session_required"
    )


def test_dirty_or_wrong_source_refuses_before_stdin_and_hides_detail(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(command, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        command,
        "validate_product_source",
        lambda *_args: (_ for _ in ()).throw(DeployProductSourceError("SECRET-PATH")),
    )
    monkeypatch.setattr(command.sys, "stdin", _UnreadableStdin())

    assert command.main(_argv("--preview")) == 2
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["failure_code"] == (
        "acceptance_source_release_unverified"
    )
    assert "SECRET-PATH" not in rendered


def test_bindings_are_bounded_extra_forbid_and_never_reflected(
    monkeypatch, capsys
) -> None:
    _allow_source(monkeypatch)
    monkeypatch.setattr(
        command.sys,
        "stdin",
        io.StringIO("x" * (command.MAX_BINDINGS_CHARACTERS + 1)),
    )
    assert command.main(_argv("--preview")) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == "bindings_too_large"

    payload = _bindings()
    payload["body"] = "MUST-NOT-REFLECT"
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(payload)))
    assert command.main(_argv("--preview")) == 2
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["failure_code"] == "bindings_invalid"
    assert "MUST-NOT-REFLECT" not in rendered


@pytest.mark.parametrize(
    "variant", ("missing", "version-extra", "nested-secret", "empty")
)
def test_bindings_reject_missing_or_nested_unknown_fields_without_reflection(
    monkeypatch, capsys, variant
) -> None:
    _allow_source(monkeypatch)
    payload = _bindings()
    if variant == "missing":
        payload.pop("claude_desktop_session_id")
    elif variant == "version-extra":
        payload["versions"]["claude-vscode"] = "MUST-NOT-REFLECT"
    elif variant == "nested-secret":
        payload["broker"]["token"] = "MUST-NOT-REFLECT"
    raw = "" if variant == "empty" else json.dumps(payload)
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(raw))

    assert command.main(_argv("--preview")) == 2
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["failure_code"] == "bindings_invalid"
    assert "MUST-NOT-REFLECT" not in rendered


def test_unreadable_bindings_emit_only_the_fixed_code(monkeypatch, capsys) -> None:
    _allow_source(monkeypatch)
    monkeypatch.setattr(command.sys, "stdin", _UnreadableStdin())
    assert command.main(_argv("--preview")) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == (
        "bindings_unreadable"
    )


def _ready_decision():
    from runtime.api.tools.session_control_live_acceptance_broker_binding import (
        BrokerBinding,
        BrokerBindingDecision,
    )

    broker = _bindings()["broker"]
    return BrokerBindingDecision(
        "ready",
        BrokerBinding(
            broker["target_session_id"],
            broker["machine_id"],
            broker["peer_session_id"],
        ),
    )


def test_preview_emits_canonical_matrix_without_live_acceptance(
    monkeypatch, capsys
) -> None:
    _allow_source(monkeypatch)
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(_bindings())))
    monkeypatch.setattr(
        command,
        "acceptance_main",
        lambda _args: (_ for _ in ()).throw(AssertionError("live run started")),
    )

    assert command.main(_argv("--preview")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready"
    assert report["project"] == "yoke"
    assert report["release_sha"] == RELEASE_SHA
    assert len(report["cells"]) == 6


def test_live_run_uses_owner_only_atomic_scratch_and_cleans_it(
    monkeypatch, tmp_path
) -> None:
    _allow_source(monkeypatch)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(_bindings())))
    observed: dict[str, object] = {}
    real_atomic_write = command.atomic_write_text
    real_ensure = command.ensure_owner_only_directory

    def _ensure(path) -> Path:
        secured = real_ensure(path)
        observed["payload_dir"] = secured
        return secured

    def _atomic_write(path, content) -> None:
        real_atomic_write(path, content)
        observed["atomic_target"] = Path(path)
        assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600

    def _acceptance_main(args: list[str]) -> int:
        matrix = Path(args[args.index("--matrix") + 1])
        observed["matrix"] = matrix
        observed["document"] = json.loads(matrix.read_text(encoding="utf-8"))
        assert stat.S_IMODE(matrix.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(matrix.stat().st_mode) == 0o600
        assert args[args.index("--release-sha") + 1] == RELEASE_SHA
        return 7

    monkeypatch.setattr(command, "ensure_owner_only_directory", _ensure)
    monkeypatch.setattr(command, "atomic_write_text", _atomic_write)
    monkeypatch.setattr(command, "acceptance_main", _acceptance_main)

    assert command.main(_argv("--timeout-seconds", "12")) == 7
    matrix = observed["matrix"]
    assert isinstance(matrix, Path)
    assert not matrix.exists()
    assert not observed["atomic_target"].exists()
    assert stat.S_IMODE(observed["payload_dir"].stat().st_mode) == 0o700
    assert observed["document"]["project"] == "yoke"


def test_candidate_run_forwards_stage_mode_to_existing_runner(
    monkeypatch, tmp_path
) -> None:
    require_exact_desktop_active_policy(monkeypatch)
    _allow_source(monkeypatch)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    bindings = _bindings()
    bindings["versions"]["claude-desktop"] = (
        CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION
    )
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(bindings)))
    observed: dict[str, object] = {}

    def _acceptance_main(args: list[str]) -> int:
        observed["args"] = args
        return 0

    monkeypatch.setattr(command, "acceptance_main", _acceptance_main)

    assert command.main(_argv("--qualification-candidate")) == 0
    assert "--qualification-candidate" in observed["args"]


def test_symlinked_payload_directory_refuses_without_writing_or_leaking_path(
    monkeypatch, tmp_path, capsys
) -> None:
    _allow_source(monkeypatch)
    run_root = tmp_path / "run"
    outside = tmp_path / "outside-secret"
    run_root.mkdir()
    outside.mkdir()
    (run_root / "payloads").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(command, "scratch_root", lambda _project: run_root)
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(_bindings())))

    assert command.main(_argv()) == 2
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["failure_code"] == "acceptance_scratch_unavailable"
    assert str(outside) not in rendered
    assert list(outside.iterdir()) == []
