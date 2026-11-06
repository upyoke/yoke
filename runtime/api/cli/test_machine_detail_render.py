"""Machine inventories stay readable without losing the complete read."""

from copy import deepcopy
from functools import partial
from io import StringIO
import json

import pytest

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.machine_detail_render import write_machine_detail
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.fixture
def detail():
    sessions = [
        {
            "session_id": f"session-{i:03}",
            "offered_at": f"2026-10-{i + 1:02}",
            "workspace": "/example/project",
            "model": "example-model",
        }
        for i in range(30)
    ]
    return {
        "machine": {"name": "workshop"},
        "relay": {
            "hostname": "workshop",
            "native_models": {
                surface: {
                    "surface": surface,
                    "status": "ok",
                    "reason": None,
                    "source": "native probe",
                    "observed_at": "2026-10-30",
                    "models": [
                        {"model": f"{surface}-model-{i}", "label": "Model " + "x" * 80}
                        for i in range(256)
                    ],
                }
                for surface in ("cursor-cli", "future-surface")
            },
        },
        "harnesses": [],
        "projects": [],
        "test_machines": [{"host": "qa-host"}],
        "surface_policies": [{"reason": "policy-marker"}],
        "running_sessions": sessions,
        "recent_sessions": sessions,
        "recent_launches": [
            {"launch_id": f"launch-{i:03}", "created_at": f"2026-10-{i + 1:02}"}
            for i in range(20)
        ],
        "token": {"status": "active"},
        "credential_presence": {"github": True},
        "offers_enforcement_note": "Reserved offers are not enforced.",
    }


def render(detail, *, full=False):
    stream = StringIO()
    write_machine_detail(detail, stream, StringIO(), full=full)
    return stream.getvalue()


def test_routine_headings_and_generic_model_summaries(detail):
    original = deepcopy(detail)
    text = render(detail)
    for title in (
        "Machine",
        "Relay",
        "Native models",
        "Harnesses",
        "Projects",
        "Running sessions",
        "Recent sessions",
        "Recent launches",
        "Token",
        "Credentials",
        "Test machines",
        "Surface policies",
    ):
        assert f"## {title}\n" in text
    for surface in ("cursor-cli", "future-surface"):
        assert f"### {surface}\n{surface}: ok; 256 models" in text
        assert f"{surface}-model-0" not in text
    assert "qa-host" in text and "policy-marker" in text
    assert detail == original


def test_session_and_launch_lists_show_newest_ten_and_recovery(detail):
    text = render(detail)
    assert text.count("Count: 30; showing 10.") == 2
    assert "Count: 20; showing 10." in text
    assert "session-029" in text and "session-020" in text
    assert "session-019" not in text
    assert "launch-019" in text and "launch-010" in text
    assert "launch-009" not in text
    assert "Use --full to show every entry." in text


def test_full_keeps_models_metadata_and_all_rows(detail):
    text = render(detail, full=True)
    for surface in detail["relay"]["native_models"]:
        for i in range(256):
            assert f"{surface}-model-{i}" in text
    assert "native probe" in text and "2026-10-30" in text
    for i in range(30):
        assert f"session-{i:03}" in text
    for i in range(20):
        assert f"launch-{i:03}" in text
    assert "Reserved offers are not enforced." in text


def test_large_read_fits_safety_net_and_json_stays_complete(detail, capsys):
    raw = FunctionCallResponse(
        success=True, function="machine.detail", version="v1", result=detail
    )
    assert len(render(detail, full=True).encode()) > REPLY_LIMIT_BYTES
    with read_output_scope([], "machine.detail", ("machine", "detail")):
        assert (
            emit_response(raw, json_mode=False, human_writer=write_machine_detail) == 0
        )
    text = capsys.readouterr()
    assert not text.err
    assert len(text.out.encode()) < REPLY_LIMIT_BYTES // 2
    assert emit_response(raw, json_mode=True, human_writer=write_machine_detail) == 0
    assert json.loads(capsys.readouterr().out)["result"] == detail


def test_full_surface_section_uses_shared_read_flags(detail, capsys):
    import argparse

    args = ["--section", "future-surface", "--full"]
    raw = FunctionCallResponse(
        success=True, function="machine.detail", version="v1", result=detail
    )
    with read_output_scope(args, "machine.detail", ("machine", "detail")):
        parse_or_usage_error(argparse.ArgumentParser(), args, "machine detail")
        assert (
            emit_response(
                raw,
                json_mode=False,
                human_writer=partial(write_machine_detail, full=True),
            )
            == 0
        )
    text = capsys.readouterr().out
    assert "future-surface-model-255" in text
    assert "cursor-cli-model" not in text
    assert "## Machine\n" not in text


def test_machine_without_relay_has_explicit_empty_models():
    text = render({"machine": {}, "relay": None})
    assert "Relay: none" in text
    assert "Native models: empty." in text
