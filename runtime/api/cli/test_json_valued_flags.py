"""JSON input sources behave alike at the CLI entry points that accept them."""

from __future__ import annotations

import codecs
import io
import json
from contextlib import nullcontext

import pytest

from yoke_cli.commands import browser_authorize, browser_verify, json_input, qa_browser
from yoke_cli.commands import browser_authorize_automatic
from yoke_cli.commands.adapters import qa_artifact_cli
from yoke_cli.config import browser_profile
from yoke_harness import browser_check_profile, browser_client, browser_qa_daemon


@pytest.fixture
def json_argument(request, tmp_path, monkeypatch):
    def argument(document):
        if request.param == "inline":
            return document
        if request.param == "stdin":
            monkeypatch.setattr("sys.stdin", io.StringIO(document))
            return "-"
        path = tmp_path / "JSON input.json"
        bom = codecs.BOM_UTF8 if request.param == "bom-file" else b""
        path.write_bytes(bom + document.encode("utf-8"))
        return f"@{path}"

    return argument


SOURCES = ["inline", "file", "bom-file", "stdin"]
ARTIFACT_ARGS = [
    "--requirement-id",
    "1",
    "--run-id",
    "2",
    "--artifact-type",
    "evidence",
    "--filename",
    "test.txt",
    "--content-base64",
    "eA==",
]
BROWSER_ARGS = ["--project", "acme", "--identity", "operator", "--json"]
STEP_ARGS = ["--base-url", "https://example.com", "--project", "acme"]


@pytest.mark.parametrize(
    "command", [browser_verify.browser_verify, browser_authorize.browser_authorize]
)
@pytest.mark.parametrize("json_argument", SOURCES, indirect=True)
def test_declarations_sources(command, json_argument, monkeypatch, capsys):
    monkeypatch.setattr(browser_profile, "profile_project_key", lambda project: project)
    monkeypatch.setattr(browser_authorize, "prepare_browser_runtime", lambda _: None)
    monkeypatch.setattr(
        browser_authorize_automatic, "authorize_automatic", lambda *args: ([], [])
    )
    document = '{"identities": {"operator": {"sites": []}}}'
    assert command([*BROWSER_ARGS, "--declarations-json", json_argument(document)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is True
    assert receipt["identity"] == "operator"


@pytest.mark.parametrize("json_argument", SOURCES, indirect=True)
def test_step_sources(json_argument, monkeypatch, capsys):
    monkeypatch.setattr(qa_browser, "required_project_context", lambda project: project)
    monkeypatch.setattr(
        browser_check_profile, "check_scope", lambda *a, **k: nullcontext()
    )
    monkeypatch.setattr(browser_qa_daemon, "ensure_daemon_running", lambda *a: None)
    monkeypatch.setattr(browser_client, "ensure_page", lambda name: name)
    monkeypatch.setattr(browser_client, "execute_step", lambda step, *a, **k: step)
    document = '{"action": "navigate", "url": "/café"}'
    assert (
        qa_browser.qa_browser_step([*STEP_ARGS, "--step-json", json_argument(document)])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(document)


@pytest.mark.parametrize("json_argument", SOURCES, indirect=True)
def test_metadata_sources_preserve_string_payload(json_argument, monkeypatch):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs["payload"])
        return 0

    monkeypatch.setattr(qa_artifact_cli, "dispatch_and_emit", dispatch)
    document = '{"subject": "café"}'
    assert (
        qa_artifact_cli.qa_artifact_add(
            [*ARTIFACT_ARGS, "--metadata", json_argument(document)]
        )
        == 0
    )
    assert calls[0]["metadata"] == document


@pytest.mark.parametrize(
    ("command", "args", "flag"),
    [
        (browser_verify.browser_verify, BROWSER_ARGS[:-1], "--declarations-json"),
        (browser_authorize.browser_authorize, BROWSER_ARGS[:-1], "--declarations-json"),
        (qa_browser.qa_browser_step, STEP_ARGS, "--step-json"),
        (qa_artifact_cli.qa_artifact_add, ARTIFACT_ARGS, "--metadata"),
    ],
)
def test_windows_malformed_inline_json_names_powershell(
    command, args, flag, monkeypatch, capsys
):
    monkeypatch.setattr(json_input, "_WINDOWS", True)
    monkeypatch.setattr(browser_profile, "profile_project_key", lambda project: project)
    assert command([*args, flag, "{identities:{}}"]) == 2
    error = capsys.readouterr().err
    assert "PowerShell drops inner quotes when calling yoke.cmd" in error
    assert f"{flag} @FILE" in error
    assert "Out-File -Encoding utf8" in error


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (None, "cannot read JSON input"),
        (b"\xff", "cannot read JSON input"),
        (b"{identities:{}}", "the file contains invalid JSON"),
    ],
)
def test_file_failures_give_source_specific_recovery(
    content, error, tmp_path, monkeypatch
):
    monkeypatch.setattr(json_input, "_WINDOWS", True)
    path = tmp_path / "settings.json"
    if content is not None:
        path.write_bytes(content)
    with pytest.raises(ValueError, match=error) as refusal:
        json_input.load_json_input(f"@{path}", "--declarations-json")
    assert "Recovery:" in str(refusal.value)
    assert "PowerShell" not in str(refusal.value)
