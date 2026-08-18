"""Canonicalize retired watch_pytest commands onto the sanctioned runner."""

from __future__ import annotations

import json

from yoke_core.domain.qa_command_invocation import (
    SANCTIONED_WATCH_PYTEST,
    canonicalize_registered_command,
    rewrite_retired_watch_pytest_commands,
)


def test_canonicalize_drops_uv_prefix_and_rewrites_the_module_form() -> None:
    assert canonicalize_registered_command(
        "uv run --frozen python3 -m yoke_core.tools.watch_pytest --impacted main"
    ) == f"{SANCTIONED_WATCH_PYTEST} --impacted main"


def test_canonicalize_keeps_args_after_a_double_dash() -> None:
    assert canonicalize_registered_command(
        "uv sync --frozen && uv run --frozen python3 -m "
        "yoke_core.tools.watch_pytest -- services/platform-svc/tests"
    ) == f"{SANCTIONED_WATCH_PYTEST} -- services/platform-svc/tests"


def test_canonicalize_leaves_already_sanctioned_commands_alone() -> None:
    command = f"{SANCTIONED_WATCH_PYTEST} --impacted main"
    assert canonicalize_registered_command(command) == command
    assert canonicalize_registered_command("python3 -m pytest") == (
        "python3 -m pytest"
    )


def test_rewrite_updates_stale_requirement_snapshots(monkeypatch) -> None:
    updates: list[object] = []

    class _Conn:
        def execute(self, sql, params):
            updates.append((sql, params))

        def commit(self) -> None:
            updates.append("commit")

    monkeypatch.setattr(
        "yoke_core.domain.qa_command_invocation.query_rows",
        lambda _conn, _sql: [{
            "id": 7,
            "method_config": json.dumps({
                "command": (
                    "uv run --frozen python3 -m "
                    "yoke_core.tools.watch_pytest --impacted main"
                ),
            }),
        }],
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_command_invocation.db_backend.connection_is_postgres",
        lambda _conn: True,
    )

    assert rewrite_retired_watch_pytest_commands(_Conn()) == 1
    assert updates[-1] == "commit"
    _sql, params = updates[0]
    assert "UPDATE qa_requirements" in _sql
    assert json.loads(params[0])["command"] == (
        f"{SANCTIONED_WATCH_PYTEST} --impacted main"
    )
    assert params[1] == 7
