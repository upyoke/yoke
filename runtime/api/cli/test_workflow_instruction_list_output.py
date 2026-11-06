"""Instruction roster defaults to descriptors and expands deliberately."""

import io
import json

import pytest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main
from yoke_contracts.api.function_call import FunctionCallResponse


def run_list(monkeypatch, *flags, instructions=None):
    monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
    rows = (
        instructions
        if instructions is not None
        else [
            {
                "id": 3,
                "content": "Build carefully\nKeep all behavior.",
                "applies_to_all_workflows": True,
                "applies_to_all_projects": False,
            },
            {"id": 8, "content": "Review results\nCheck the evidence."},
        ]
    )

    def dispatch(request):
        assert request.payload == {}
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"instructions": rows, "delivery_options": {"stage_buckets": []}},
        )

    out, err = io.StringIO(), io.StringIO()
    with (
        patch("yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=dispatch),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = main(["workflow", "execution-instruction", "list", *flags])
    assert code == 0, err.getvalue()
    return out.getvalue()


def test_default_lists_id_and_first_line_without_body(monkeypatch):
    out = run_list(monkeypatch)
    assert "3  Build carefully" in out
    assert "8  Review results" in out
    assert "Keep all behavior." not in out
    assert "Check the evidence." not in out
    assert "yoke workflow execution-instruction list --full" in out


def test_full_has_selectable_heading_and_complete_content(monkeypatch):
    out = run_list(monkeypatch, "--full")
    assert "## 3 Build carefully\nBuild carefully\nKeep all behavior." in out
    assert "## 8 Review results\nReview results\nCheck the evidence." in out


def test_full_section_selects_one_instruction(monkeypatch):
    out = run_list(monkeypatch, "--full", "--section", "3 Build carefully")
    assert "Keep all behavior." in out
    assert "Check the evidence." not in out


def test_json_keeps_content_and_scope(monkeypatch):
    result = json.loads(run_list(monkeypatch, "--json"))["result"]
    assert result["instructions"][0]["content"].endswith("Keep all behavior.")
    assert result["instructions"][0]["applies_to_all_workflows"] is True
    assert "delivery_options" in result


@pytest.mark.parametrize("flags", [[], ["--full"]])
def test_empty_instruction_list_is_explicit(monkeypatch, flags):
    assert "No operator execution instructions" in run_list(
        monkeypatch, instructions=[]
    )
