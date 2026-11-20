"""Browser approvals run in the test machine's operator identity browser."""

from __future__ import annotations

import shlex

import pytest

from yoke_contracts.browser_identity import BrowserIdentityError
from yoke_core.domain import machine_qa_operator_browser as operator

GATE = {"step": "approve", "operator_gate": "machine_browser_approval"}
DECLARED = {"identities": {"operator": {"sites": []}}, "default_identity": "operator"}


def _with(monkeypatch, settings, actions=(GATE,), os_name="linux"):
    monkeypatch.setattr(operator, "_browser_settings", lambda conn, pid: settings)
    config = {"actions": list(actions)}
    return operator.with_operator_browser(
        config,
        identity=operator.operator_identity(object(), 1, [{"method_config": config}]),
        project="acme",
        test_machine="linux-lab",
        os_name=os_name,
    )


def test_a_browser_approval_names_the_project_default_identity(monkeypatch):
    config = _with(monkeypatch, DECLARED)
    assert config[operator.OPERATOR_BROWSER] == {
        "project": "acme",
        "identity": "operator",
        "test_machine": "linux-lab",
        "os": "linux",
    }
    assert operator.reauthorize_command(config) == (
        "yoke browser authorize --project acme --identity operator "
        "--test-machine linux-lab"
    )


@pytest.mark.parametrize(
    ("actions", "os_name"),
    [((), "linux"), (({"step": "x"},), "macos"), ((), "windows")],
)
def test_recipes_without_a_browser_approval_are_unchanged(
    monkeypatch, actions, os_name
):
    config = _with(monkeypatch, {}, actions=actions, os_name=os_name)
    assert operator.OPERATOR_BROWSER not in config
    assert operator.browser_export(config) == ""


def test_an_undeclared_operator_identity_refuses_with_the_setting_to_add(monkeypatch):
    with pytest.raises(BrowserIdentityError) as refusal:
        _with(monkeypatch, {"identities": DECLARED["identities"]})
    message = str(refusal.value)
    assert message.startswith("machine_operator_identity_undeclared:")
    assert "--set default_identity=NAME" in message
    assert "--test-machine linux-lab" in message


def test_the_export_routes_links_to_the_launcher_with_the_users_store(monkeypatch):
    config = _with(monkeypatch, DECLARED)
    prefix = operator.browser_export(config)
    words = shlex.split(prefix.removesuffix("; "))
    assert words[:1] == ["export"]
    name, _, value = words[1].partition("=")
    assert name == "BROWSER"
    assert value == (
        "env -u YOKE_MACHINE_HOME {yoke_bin} browser open --project acme "
        "--identity operator %s"
    )


def test_the_server_contract_carries_the_identity_to_a_connectionless_runner(
    monkeypatch,
):
    from types import SimpleNamespace

    from yoke_contracts.machine_qa_execution import HostControlExecutionContract
    from yoke_core.domain import machine_qa_local_execution as local

    monkeypatch.setattr(operator, "_browser_settings", lambda conn, pid: DECLARED)
    cases = [{"method_config": {"actions": [GATE]}}]
    assert operator.operator_identity(object(), 1, cases) == "operator"
    assert operator.operator_identity(object(), 1, [{"method_config": {}}]) is None
    contract = HostControlExecutionContract.model_construct(
        project_id=1,
        project="acme",
        settings={"resource_name": "linux-lab"},
        cases=[],
        plan_execution_id=None,
        continues_execution_id=None,
        lease_id=7,
        operator_identity="operator",
    )
    control = SimpleNamespace(mission_scratch_path=lambda value: value)
    monkeypatch.setattr(
        local, "resolve_contract_host_control", lambda raw: (control, object())
    )
    lease = local._execution(contract)
    # The local runner holds no database connection; the contract is its source.
    assert lease.conn is None and lease.operator_identity == "operator"
