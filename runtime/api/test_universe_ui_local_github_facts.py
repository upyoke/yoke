"""The local UI server's part of the shared GitHub page.

The local server names this machine's GitHub account for the Personal
panel and routes the page's Check now through this machine's GitHub App
user authorization; every other admitted call dispatches unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import reader as machine_config
from yoke_core.ui import function_proxy, local_github_facts, proxy_transport, server


def _stub_github_config(monkeypatch, value):
    def read(path=None):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(machine_config, "github_config", read)


def test_a_connected_machine_names_its_account(monkeypatch):
    _stub_github_config(
        monkeypatch,
        {
            "authorization": {"login": "octo", "status": "authorized", "kind": "x"},
        },
    )

    assert local_github_facts.machine_github_facts() == {
        "authorization": {"login": "octo", "status": "authorized"},
    }


@pytest.mark.parametrize("config", [{}, {"authorization": {"status": "authorized"}}])
def test_an_unconnected_machine_has_no_account(monkeypatch, config):
    _stub_github_config(monkeypatch, config)

    assert local_github_facts.machine_github_facts() == {"authorization": None}


def test_an_unreadable_config_says_so(monkeypatch):
    _stub_github_config(monkeypatch, machine_config.MachineConfigError("bad"))

    assert local_github_facts.machine_github_facts() == {
        "authorization": None,
        "notices": [{"kind": "error", "message": local_github_facts.UNREADABLE_NOTICE}],
    }


def test_local_capabilities_carry_the_github_facts(monkeypatch):
    facts = {"authorization": {"login": "octo", "status": "authorized"}}
    monkeypatch.setattr(local_github_facts, "machine_github_facts", lambda: facts)

    data = server._local_capabilities()["data"]

    assert data["github"] == facts
    assert data["portability"]["mode"] == "local"


def test_the_check_is_an_admitted_ui_mutation():
    assert (
        "projects.github_binding.check" in function_proxy.UI_MUTATION_FUNCTION_ALLOWLIST
    )


def _record_dispatch(monkeypatch):
    import yoke_core.domain.yoke_function_dispatch as dispatch_module

    dispatched = []
    monkeypatch.setattr(
        dispatch_module,
        "dispatch",
        lambda request, **kwargs: dispatched.append(request.function) or "result",
    )
    return dispatched


def test_the_check_dispatches_with_machine_github_authorization(monkeypatch):
    from yoke_cli.transport import local_github_dispatch

    dispatched = _record_dispatch(monkeypatch)
    wrapped = []

    def wrap(request, run, *, core_available):
        wrapped.append((request.function, core_available))
        return run(request)

    monkeypatch.setattr(
        local_github_dispatch, "call_with_machine_github_authorization", wrap
    )

    result = proxy_transport.dispatch_in_process(
        SimpleNamespace(function="projects.github_binding.check"),
    )

    assert result == "result"
    assert wrapped == [("projects.github_binding.check", True)]
    assert dispatched == ["projects.github_binding.check"]


def test_other_calls_dispatch_without_machine_authorization(monkeypatch):
    from yoke_cli.transport import local_github_dispatch

    dispatched = _record_dispatch(monkeypatch)
    monkeypatch.setattr(
        local_github_dispatch,
        "call_with_machine_github_authorization",
        lambda *args, **kwargs: pytest.fail("unexpected machine authorization"),
    )

    proxy_transport.dispatch_in_process(
        SimpleNamespace(function="projects.github_binding.status"),
    )

    assert dispatched == ["projects.github_binding.status"]
