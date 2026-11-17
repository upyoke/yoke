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
    return operator.with_operator_browser(
        {"actions": list(actions)},
        conn=object(),
        project_id=1,
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
