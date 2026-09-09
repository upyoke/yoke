"""Registration refusals name the env a checkout is actually mapped under.

Every client-side session registration path resolves the checkout→project
mapping under the selected connection env and refuses when nothing
resolves. The refusal is correct — project ids do not cross universes —
but on its own it reads as *unconfigured*. These cover each path naming
the registered env instead, and none of them registering anything into
the wrong universe on the way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain import machine_config_writer
from yoke_core.hooks import session_lifecycle_client


@pytest.fixture()
def mapped_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout registered under ``local`` while ``upyoke`` is selected."""
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
    checkout = tmp_path / "mini"
    checkout.mkdir()
    machine_config_writer.register_project(checkout, 4, path=cfg)
    monkeypatch.setenv("YOKE_ENV", "upyoke")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(cfg))
    return checkout


def _refuse_registration_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any registration attempt from here would land in the wrong universe."""
    monkeypatch.setattr(
        session_lifecycle_client, "_relay_owns_registration", lambda: False,
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_local_authority_active",
        lambda: pytest.fail("a mapping-less checkout must not register"),
    )


def _register(root: Path) -> str:
    return session_lifecycle_client.register_harness_session(
        root=str(root),
        session_id="s-1",
        executor="claude-code",
        provider="anthropic",
        model_facts=SessionModelFacts(requested_model="claude-opus-5"),
        native_thread_id="",
    )


def test_hook_registration_refusal_names_both_envs_and_both_recoveries(
    mapped_elsewhere: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _refuse_registration_writes(monkeypatch)

    error = _register(mapped_elsewhere)

    assert "requires a configured project_id" in error
    assert "project 4 on env local" in error
    assert "the selected env is upyoke" in error
    assert "`yoke env use local`" in error
    assert f"`yoke project register {mapped_elsewhere} --project-id N`" in error


def test_a_genuinely_unconfigured_checkout_keeps_the_setup_wording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _refuse_registration_writes(monkeypatch)

    error = _register(tmp_path)

    assert error == (
        "session registration requires a configured project_id for this checkout."
    )


def test_a_matching_mapping_registers_instead_of_refusing(
    mapped_elsewhere: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_ENV", "local")
    monkeypatch.setattr(
        session_lifecycle_client, "_relay_owns_registration", lambda: False,
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_local_authority_active", lambda: True,
    )
    seen: list[int] = []
    monkeypatch.setattr(
        "yoke_core.hooks.registration._register_in_process",
        lambda *_a, project_id=None, **_k: seen.append(project_id) or "",
    )

    assert _register(mapped_elsewhere) == ""
    assert seen == [4]


def test_session_begin_adapter_refusal_names_the_registered_env(
    mapped_elsewhere: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from yoke_core.api import service_client_sessions_lifecycle_begin as begin

    code = begin.cmd_session_begin([
        "--session-id", "s-1",
        "--executor", "claude-code",
        "--provider", "anthropic",
        "--workspace", str(mapped_elsewhere),
    ])

    assert code == 2
    err = capsys.readouterr().err
    assert "Run Yoke setup for this checkout or pass --project-id." in err
    assert "project 4 on env local" in err
    assert "the selected env is upyoke" in err


def test_sessions_begin_cli_refusal_names_the_registered_env(
    mapped_elsewhere: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from yoke_cli.commands.adapters import sessions

    code = sessions.sessions_begin([
        "--executor", "claude-code",
        "--provider", "anthropic",
        "--requested-model", "claude-opus-5",
        "--workspace", str(mapped_elsewhere),
    ])

    assert code == 2
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "Run Yoke setup for this checkout or pass --project." in output
    assert "project 4 on env local" in output
    assert "the selected env is upyoke" in output
