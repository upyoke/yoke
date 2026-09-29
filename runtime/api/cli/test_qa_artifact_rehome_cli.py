"""``yoke qa artifact rehome`` sends the capture machine's recorded bytes."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from yoke_cli.commands.adapters import qa_artifact_rehome_cli as cli
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


def _response(function: str, result: dict | None = None, error: str = "") -> Any:
    return FunctionCallResponse(
        success=not error,
        function=function,
        version="v1",
        request_id="r",
        result=result,
        error=FunctionError(code=error, message=error) if error else None,
    )


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(cli, "emit_response", lambda response, json_mode: 0)
    return calls


def _dispatcher(monkeypatch, calls, read_result: dict) -> None:
    def call(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs["function_id"] == "qa.artifact.read":
            return _response("qa.artifact.read", read_result)
        return _response("qa.artifact.rehome", {"rehomed": True})

    monkeypatch.setattr(cli, "call_dispatcher", call)


def test_recorded_bytes_are_sent_for_each_artifact(
    tmp_path, monkeypatch, dispatched
) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"PNG bytes")
    _dispatcher(
        monkeypatch,
        dispatched,
        {"backend": "local", "disposition": "evidence_on_machine",
         "recorded_path": str(shot)},
    )

    code = cli.qa_artifact_rehome(
        ["--requirement-id", "7", "--artifact-id", "70", "--artifact-id", "71"]
    )

    assert code == 0
    rehomes = [c for c in dispatched if c["function_id"] == "qa.artifact.rehome"]
    assert [c["payload"]["artifact_id"] for c in rehomes] == [70, 71]
    assert base64.b64decode(rehomes[0]["payload"]["content_base64"]) == b"PNG bytes"
    assert rehomes[0]["target"].qa_requirement_id == 7


def test_object_store_artifact_needs_no_move(monkeypatch, dispatched, capsys) -> None:
    _dispatcher(monkeypatch, dispatched, {"backend": "s3", "disposition": "ready"})

    assert cli.qa_artifact_rehome(["--requirement-id", "7", "--artifact-id", "70"]) == 0
    assert [c["function_id"] for c in dispatched] == ["qa.artifact.read"]
    assert "already in the object store" in capsys.readouterr().out


def test_bytes_missing_here_name_the_capture_machine(
    tmp_path, monkeypatch, dispatched, capsys
) -> None:
    _dispatcher(
        monkeypatch,
        dispatched,
        {"backend": "local", "recorded_path": str(tmp_path / "gone.png"),
         "machine": "Capture Mac"},
    )

    assert cli.qa_artifact_rehome(["--requirement-id", "7", "--artifact-id", "70"]) == 1
    err = capsys.readouterr().err
    assert "Run this recovery on Capture Mac" in err
    assert [c["function_id"] for c in dispatched] == ["qa.artifact.read"]


def test_serving_build_without_recorded_paths_is_named(
    monkeypatch, dispatched, capsys
) -> None:
    _dispatcher(
        monkeypatch, dispatched, {"backend": "local", "disposition": "evidence_on_machine"}
    )

    assert cli.qa_artifact_rehome(["--requirement-id", "7", "--artifact-id", "70"]) == 1
    assert "older than this recovery" in capsys.readouterr().err
