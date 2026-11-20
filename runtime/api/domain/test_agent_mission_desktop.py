"""yoke qa mission desktop: lease routing, stdin text, results and refusals."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_contracts.desktop_input import DesktopInputRefused
from yoke_contracts.test_machine_types import HostActionResult
from yoke_cli.commands import qa_case
from yoke_cli.commands.qa_mission import qa_mission_desktop
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_core.domain import agent_mission_desktop_cli as cli
from yoke_core.domain import machine_qa_local_execution as local

FLAGS = ["--execution-id", "exec-1", "--requirement-id", "9"]


@pytest.fixture
def leased(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "resolve_mission_contract", lambda parsed, prog: {"op": 1})
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )

    def execute(contract, request):
        calls.append(request)
        if request["action"] == "focus":
            return {"ok": False, "error_code": "windows_window_not_found",
                    "detail": "no visible window matches", "recovery": "list windows"}
        return {"ok": True, "error_code": None, "action": request["action"],
                **({"typed_characters": len(request["text"])} if "text" in request else {})}

    monkeypatch.setattr(cli, "execute_agent_mission_desktop", execute)
    return calls


def test_type_reads_text_from_stdin_and_prints_only_its_length(leased, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("hello world\n"))
    assert cli.run([*FLAGS, "type", "--title", "Codex", "--text-stdin"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["typed_characters"] == 11 and "hello" not in json.dumps(printed)
    assert leased[0]["text"] == "hello world"


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["type", "--title", "Codex"], "desktop_input_text_missing"),
        (["keys", "--title", "C", "--keys", "enter", "--text-stdin"], "desktop_input_option_unused"),
        (["click", "--title", "C"], "desktop_input_click_target_invalid"),
    ],
)
def test_bad_requests_refuse_before_resolving_the_lease(leased, capsys, args, code):
    assert cli.run([*FLAGS, *args]) == 1
    assert f"{code}:" in capsys.readouterr().err
    assert leased == []


def test_host_refusal_prints_json_and_named_error_and_exits_1(leased, capsys):
    assert cli.run([*FLAGS, "focus", "--title", "Nope"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error_code"] == "windows_window_not_found"
    assert "windows_window_not_found: no visible window matches" in captured.err
    assert "list windows" in captured.err


def test_unsupported_host_refuses_naming_the_os_route(monkeypatch):
    execution = SimpleNamespace(control=object(), material=SimpleNamespace(secrets={}))
    contract = SimpleNamespace(settings={"os": "macos"})
    monkeypatch.setattr(local, "_mission_contract", lambda raw: contract)
    monkeypatch.setattr(local, "_execution", lambda c: execution)
    with pytest.raises(DesktopInputRefused) as caught:
        cli.execute_agent_mission_desktop({}, {"action": "windows"})
    assert caught.value.code == "desktop_input_unsupported_os"
    assert "osascript" in caught.value.recovery


def test_results_are_redacted_and_passed_lease_secrets(monkeypatch):
    seen = {}

    class Control:
        def drive_desktop(self, request, *, secrets):
            seen["secrets"] = secrets
            return HostActionResult(True, {"windows": [{"title": "token s3cret"}]})

    execution = SimpleNamespace(
        control=Control(), material=SimpleNamespace(secrets={"k": "s3cret"})
    )
    monkeypatch.setattr(local, "_mission_contract", lambda raw: SimpleNamespace(settings={}))
    monkeypatch.setattr(local, "_execution", lambda c: execution)
    result = cli.execute_agent_mission_desktop({}, {"action": "windows"})
    assert seen["secrets"] == ("s3cret",)
    assert result["windows"][0]["title"] == "token [REDACTED]"


def test_desktop_token_routes_to_detached_adapter():
    resolved = resolve_tool_shaped(["qa", "mission", "desktop", *FLAGS, "windows"])
    assert resolved is not None
    adapter, rest = resolved
    assert adapter is qa_mission_desktop
    process = mock.Mock()
    process.wait.return_value = 0
    with (
        mock.patch.object(qa_case, "build_actor", return_value=mock.Mock(session_id="s")),
        mock.patch.object(qa_case.subprocess, "Popen", return_value=process) as popen,
    ):
        assert qa_mission_desktop(rest) == 0
    assert popen.call_args.args[0][1:3] == [
        "-m",
        "yoke_core.domain.agent_mission_desktop_cli",
    ]
