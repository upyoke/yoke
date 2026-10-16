"""Deterministic registered-client context for hook relay protocol tests."""

from types import SimpleNamespace

import pytest
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.hook_runner.project_scope import HookProjectScope

_RESOLVE = "yoke_cli.transport.https.resolve_https_connection"

_HOME_FACT = {"_yoke_client_machine_home": {"schema": 1, "root": "/home"}}


@pytest.fixture(autouse=True)
def local_subset(monkeypatch):
    """Pin the relay's client-side half to a deterministic allow."""
    from yoke_harness.hooks.local_subset import LocalSubsetEvaluation

    holder = SimpleNamespace(
        result=LocalSubsetEvaluation("", 0, False, _HOME_FACT),
        calls=[],
    )

    def fake(
        event_name,
        stdin_data,
        executor,
        agent_type,
        deadline,
        *,
        collect_facts=False,
        lint_config_snapshot=None,
        project_scope=None,
    ):
        holder.calls.append(
            (
                event_name,
                executor,
                agent_type,
                collect_facts,
                lint_config_snapshot,
            )
        )
        return holder.result

    monkeypatch.setattr(
        "yoke_harness.hooks.relay.evaluate_local_subset",
        fake,
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.lint_config_snapshot",
        lambda _payload: {},
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.resolve_hook_project_scope",
        lambda _payload: HookProjectScope(7),
    )
    return holder


@pytest.fixture()
def https_connection(monkeypatch):
    connection = HttpsConnection(api_url="https://env.example", token="tok")
    monkeypatch.setattr(_RESOLVE, lambda: connection)
    return connection
