"""Regression coverage for shared machine and ambient identity isolation."""

from __future__ import annotations

import os

from yoke_cli.config import machine_config
from yoke_contracts.cursor_session_map import CURSOR_CONVERSATION_ENV_VAR
from yoke_contracts.harness_family_identity import YOKE_SESSION_ENV_VAR
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain import session_process_anchors
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

from runtime.api.fixtures.runtime import isolate_test_machine_and_session_identity


def _contaminate_identity(monkeypatch) -> None:
    for name in AMBIENT_ENV_VARS:
        monkeypatch.setenv(name, f"ambient-{name.lower()}")
    monkeypatch.setenv(CURSOR_CONVERSATION_ENV_VAR, "ambient-conversation")


def test_isolation_ignores_external_machine_config_and_identity(
    tmp_path,
    monkeypatch,
) -> None:
    sentinel_home = tmp_path / "external-machine-home"
    sentinel_home.mkdir()
    sentinel_config = sentinel_home / machine_config.DEFAULT_CONFIG_NAME
    sentinel_body = '{"sentinel": "must-stay-unread"}\n'
    sentinel_config.write_text(sentinel_body, encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(sentinel_home))
    _contaminate_identity(monkeypatch)

    isolated_home = isolate_test_machine_and_session_identity(
        tmp_path / "isolated-case",
        monkeypatch,
    )

    assert machine_config.yoke_home() == isolated_home
    assert machine_config.load_config() == {}
    assert sentinel_config.read_text(encoding="utf-8") == sentinel_body
    assert not [name for name in AMBIENT_ENV_VARS if os.environ.get(name)]
    assert CURSOR_CONVERSATION_ENV_VAR not in os.environ
    assert session_process_anchors.anchors_dir().is_relative_to(isolated_home)
    assert resolve_ambient_session_id() is None


def test_consecutive_isolation_bindings_do_not_share_config(
    tmp_path,
    monkeypatch,
) -> None:
    first_config = None
    with monkeypatch.context() as first_patch:
        first_home = isolate_test_machine_and_session_identity(
            tmp_path / "first-case",
            first_patch,
        )
        first_config = first_home / machine_config.DEFAULT_CONFIG_NAME
        first_config.write_text('{"case": "first"}\n', encoding="utf-8")
        assert machine_config.load_config() == {"case": "first"}

    with monkeypatch.context() as second_patch:
        isolate_test_machine_and_session_identity(
            tmp_path / "second-case",
            second_patch,
        )
        assert machine_config.load_config() == {}

    assert first_config is not None
    assert first_config.read_text(encoding="utf-8") == '{"case": "first"}\n'


def test_isolation_can_seed_one_synthetic_session(tmp_path, monkeypatch) -> None:
    _contaminate_identity(monkeypatch)

    isolate_test_machine_and_session_identity(
        tmp_path / "seeded-case",
        monkeypatch,
        session_id="synthetic-test-session",
    )

    assert os.environ[YOKE_SESSION_ENV_VAR] == "synthetic-test-session"
    assert not [
        name
        for name in AMBIENT_ENV_VARS
        if name != YOKE_SESSION_ENV_VAR and os.environ.get(name)
    ]
    assert CURSOR_CONVERSATION_ENV_VAR not in os.environ
    assert resolve_ambient_session_id() == "synthetic-test-session"
