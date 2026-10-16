"""Public agent adapters must relay without loading a database client."""

import io
import json

import pytest

from yoke_cli.commands.adapters.hard_blocks import hard_blocks
from yoke_cli.commands.adapters.reflection_capture import reflection_capture
from yoke_cli.transport import dispatcher, https


@pytest.fixture
def relayed(monkeypatch):
    requests = []
    result = {"blockers": []}
    monkeypatch.setenv("YOKE_SESSION_ID", "capturing-session")
    monkeypatch.delenv("YOKE_PG_DSN", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN_FILE", raising=False)
    monkeypatch.setattr(
        https,
        "resolve_https_connection",
        lambda **kwargs: https.HttpsConnection(
            api_url="https://control.example",
            token="test-token",
            env="test",
        ),
    )

    def no_local(*args, **kwargs):
        pytest.fail("HTTPS client attempted local engine dispatch")

    monkeypatch.setattr(dispatcher, "_call_local", no_local)

    def post(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer test-token"
        assert request.full_url == "https://control.example/v1/functions/call"
        body = json.loads(request.data)
        requests.append(body)
        return io.BytesIO(
            json.dumps(
                {
                    "success": True,
                    "function": body["function"],
                    "request_id": body["request_id"],
                    "version": "v1",
                    "result": result,
                }
            ).encode()
        )

    monkeypatch.setattr(https, "open_no_redirect", post)
    return requests, result


@pytest.mark.parametrize("point", ["activation", "integration", "closure"])
def test_blocker_route_preserves_subject_filter_and_exit_status(relayed, capsys, point):
    requests, result = relayed
    ref = f"EXT-{42}"
    assert hard_blocks([ref, "--gate-point", point]) == 0
    request = requests[-1]
    assert request["target"]["public_ref"] == ref
    assert request["payload"] == {"gate_filter": point}
    assert request["actor"]["session_id"] == "capturing-session"
    line = f"BLOCKED|EXT-{11}|idea|Upstream|{point}|status:done|unsatisfied"
    result["blockers"] = [line]
    assert hard_blocks([ref, "--gate-point", point]) == 1
    assert line in capsys.readouterr().out


def test_reflection_route_sends_complete_text_and_project(relayed, tmp_path):
    requests, _ = relayed
    source = tmp_path / "response.txt"
    source.write_text("whole response\n---REFLECTION-START---\nbody\n")
    assert (
        reflection_capture(
            [
                "--text-file",
                str(source),
                "--project",
                "external",
                "--default-agent",
                "engineer",
                "--json",
            ]
        )
        == 0
    )
    request = requests[-1]
    assert request["function"] == "ouroboros.reflection.capture"
    assert request["target"]["project_id"] == "external"
    assert request["payload"] == {
        "text": source.read_text(),
        "default_agent": "engineer",
    }
    assert request["actor"]["session_id"] == "capturing-session"


def test_invalid_gate_filter_never_dispatches(relayed):
    requests, _ = relayed
    assert hard_blocks([f"EXT-{42}", "--gate-point", "typo"]) == 2
    assert requests == []


@pytest.mark.parametrize("options", [[], ["--gate-point", "all"]])
def test_unfiltered_gate_preserves_complete_evaluation(relayed, options):
    requests, _ = relayed
    assert hard_blocks([f"EXT-{42}", *options]) == 0
    assert requests[-1]["payload"] == {"gate_filter": ""}
