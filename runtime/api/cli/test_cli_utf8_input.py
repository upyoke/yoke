"""Exercise the real CLI entry point with byte pipes on the Windows CI runner."""

from __future__ import annotations

import codecs
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.windows
TEXT = "café — ✓ 😀"
COMMANDS = {
    "message": ["messages", "send", "--actor", "1"],
    "feedback": ["feedback", "--to", "yoke", "--category", "observation"],
    "progress": ["items", "progress-log", "append", "TEST-1", "--headline", "checkpoint"],
    "hook": ["hook", "evaluate", "UserPromptSubmit"],
}

# Keep routing, option parsing, and input handling real. Capture only where
# adapters would send or evaluate the decoded text, without a live service.
CLI_CAPTURE = """
import json
import sys
from yoke_cli import feedback_delivery, feedback_reporter
from yoke_cli.commands.adapters import hooks, items, session_control_messages
from yoke_cli.main import main
from yoke_contracts.hook_runner import folder_scope

def record(value):
    print(json.dumps(value))
    return 0

session_control_messages.dispatch_and_emit = lambda **kw: record(kw["payload"]["body"])
items.dispatch_and_emit = lambda **kw: record(kw["payload"]["content"])
feedback_reporter.feedback_provenance = lambda session: dict(
    reporter_email="qa@example.test", yoke_version="test", agent="test"
)
feedback_delivery.send_feedback = lambda **kw: record(kw["evidence"])
folder_scope.folder_scope = lambda raw: "registered"
hooks.require_payload_directory = lambda raw: None
hooks._dispatch_hook = lambda args, raw: record(json.loads(raw)["prompt"])
sys.exit(main(sys.argv[1:]))
"""


def run_cli(tmp_path: Path, args: list[str], data: bytes) -> subprocess.CompletedProcess:
    script = tmp_path / "cli_capture.py"
    script.write_text(CLI_CAPTURE, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict"}
    env.pop("YOKE_HOOKS_OFF", None)
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=data,
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=30,
    )


@pytest.mark.parametrize("reader", COMMANDS)
@pytest.mark.parametrize("bom", [b"", codecs.BOM_UTF8], ids=["plain", "bom"])
def test_cli_decodes_utf8_stdin(tmp_path, reader, bom):
    args = COMMANDS[reader]
    if reader == "hook":
        source = json.dumps({"prompt": TEXT}, ensure_ascii=False)
    else:
        args = [*args, "--stdin"]
        source = TEXT
    result = run_cli(tmp_path, args, bom + source.encode("utf-8"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == TEXT


@pytest.mark.parametrize("reader", COMMANDS)
@pytest.mark.parametrize("data", [b"caf\xe9", b"\xef\xbb"], ids=["cp1252", "truncated-bom"])
def test_cli_refuses_non_utf8_stdin_before_dispatch(tmp_path, reader, data):
    args = COMMANDS[reader]
    if reader != "hook":
        args = [*args, "--stdin"]
    result = run_cli(tmp_path, args, data)
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"stdin_invalid_utf8" in result.stderr
    assert b"Encode the input as UTF-8 and retry" in result.stderr
    assert b"Traceback" not in result.stderr


@pytest.mark.parametrize("data", [codecs.BOM_UTF8 + TEXT.encode("utf-8"), b"caf\xe9", b"\xef\xbb"])
def test_shared_content_file_reader(tmp_path, data):
    source = tmp_path / "content.txt"
    source.write_bytes(data)
    result = run_cli(tmp_path, [*COMMANDS["progress"], "--content-file", str(source)], b"")
    if data.startswith(codecs.BOM_UTF8):
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == TEXT
    else:
        assert result.returncode != 0
        assert result.stdout == b""
        assert b"text_file_invalid_utf8" in result.stderr
        assert b"Save the file as UTF-8" in result.stderr
