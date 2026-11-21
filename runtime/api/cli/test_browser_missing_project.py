"""Browser identity commands and the router refuse a missing project plainly."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from yoke_contracts.project_defaults import MissingProjectError
from yoke_cli import command_router as router
from yoke_cli.config import connection_selection, project_selection
from yoke_harness import harness_sandbox_recovery


@pytest.fixture
def no_project(monkeypatch):
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded", lambda: None
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=True, result={"rows": [{"slug": "mine"}]}
        ),
    )
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized",
        lambda: pytest.fail("missing project must not materialize the browser"),
    )


COMMANDS = [
    ("verify", ["--identity", "operator"]),
    ("authorize", ["--identity", "operator"]),
    ("authorize", ["--identity", "operator", "--test-machine", "win-box"]),
]
IDS = ["verify", "authorize", "authorize-test-machine"]


def _run(command, args):
    from yoke_cli.commands.browser_authorize import browser_authorize
    from yoke_cli.commands.browser_verify import browser_verify

    adapter = browser_verify if command == "verify" else browser_authorize
    return adapter(args)


@pytest.mark.parametrize(("command", "args"), COMMANDS, ids=IDS)
def test_browser_identity_commands_refuse_without_project(
    no_project, capsys, command, args
):
    assert _run(command, args) == 2
    output = capsys.readouterr()
    text = output.out + output.err
    assert "project_required" in text
    assert "Accessible projects: mine" in text
    assert "Traceback" not in text


@pytest.mark.parametrize(("command", "args"), COMMANDS, ids=IDS)
def test_browser_identity_commands_refuse_as_json(no_project, capsys, command, args):
    assert _run(command, [*args, "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"].startswith("project_required: ")
    assert set(payload) == {"ok", "error"}


def test_router_backstops_missing_project(monkeypatch, capsys):
    monkeypatch.setattr(
        connection_selection, "command_connection", lambda *a: nullcontext()
    )
    for name in (
        "control_plane_locality",
        "propagated_session_identity",
        "read_output_scope",
    ):
        monkeypatch.setattr(router, name, lambda *a: nullcontext())
    monkeypatch.setattr(harness_sandbox_recovery, "sandbox_recovery", lambda: None)

    def adapter(_args):
        raise MissingProjectError("project_required: no project given — pass --project P.")

    monkeypatch.setattr(
        router, "resolve", lambda args: (tuple(args[:2]), None, adapter, args[2:])
    )
    assert router.route_command(["things", "show"]) == 2
    output = capsys.readouterr()
    assert output.err == "yoke: project_required: no project given — pass --project P.\n"
    assert "Traceback" not in output.out + output.err
