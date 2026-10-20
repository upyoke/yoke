"""Atomic output refusal and registry coverage for CLI reads."""

import json
import re
from pathlib import Path

import pytest

from yoke_cli.transport.output_limit import (
    REPLY_LIMIT_BYTES,
    read_output_scope,
)
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.registered_reads import READ_FUNCTION_IDS
from runtime.api.tools.read_function_catalog import registered_read_ids


def response(function="qa.plan.list", result=None):
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result or {}
    )


def test_read_catalog_matches_all_registrations():
    assert READ_FUNCTION_IDS == registered_read_ids()


@pytest.mark.parametrize("json_mode", [True, False])
@pytest.mark.parametrize("function", ["qa.plan.list", "onboard.checklist.get"])
def test_oversized_read_refuses_without_partial_answer(capsys, json_mode, function):
    raw = response(function, {"rows": [{"secret_marker": "x" * REPLY_LIMIT_BYTES}]})
    assert emit_response(raw, json_mode=json_mode) == 0
    output = capsys.readouterr()
    artifact = (
        Path(json.loads(output.out)["saved_response"])
        if json_mode
        else Path(re.search(r"Complete reply saved: (.+)", output.out)[1])
    )
    assert json.loads(artifact.read_text())["response"]["result"] == raw.result
    assert len((output.out + output.err).encode()) <= REPLY_LIMIT_BYTES
    assert "--full" in output.out
    artifact.unlink()


def test_human_writer_stderr_is_bounded_atomically(capsys):
    def writer(raw, stdout, stderr):
        print("partial answer", file=stdout)
        print("é" * REPLY_LIMIT_BYTES, file=stderr)

    assert emit_response(response(), json_mode=False, human_writer=writer) == 1
    output = capsys.readouterr()
    assert "partial answer" not in output.out
    assert "essential_output_limit_exceeded" in output.err


@pytest.mark.parametrize("json_mode", [True, False])
@pytest.mark.parametrize("function", ["qa.plan.list", "onboard.checklist.get"])
def test_full_returns_every_byte(capsys, json_mode, function):
    value = "z" * (REPLY_LIMIT_BYTES + 1)
    with read_output_scope(["--full"]):
        assert (
            emit_response(response(function, {"body": value}), json_mode=json_mode) == 0
        )
    output = capsys.readouterr().out
    if json_mode:
        assert value in output
    else:
        artifact = Path(re.search(r"Complete reply saved: (.+)", output)[1])
        assert json.loads(artifact.read_text())["response"]["result"]["body"] == value
        artifact.unlink()


def test_full_does_not_escape_its_invocation():
    from yoke_cli.transport.output_limit import full_output_requested

    with read_output_scope(["--full"]):
        assert full_output_requested()
    assert not full_output_requested()
    with read_output_scope(["--", "--full"]):
        assert not full_output_requested()


def test_mutation_receipt_is_saved_without_repeating_the_write(capsys):
    value = "m" * (REPLY_LIMIT_BYTES + 1)
    assert emit_response(response("items.create", {"body": value}), json_mode=True) == 0
    pointer = json.loads(capsys.readouterr().out)
    assert pointer["success"] is True
    artifact = Path(pointer["saved_response"])
    assert json.loads(artifact.read_text())["response"]["result"]["body"] == value
    artifact.unlink()


def test_registered_read_help_teaches_full_without_requesting_it():
    import argparse
    from yoke_cli.commands._helpers import parse_or_usage_error

    parser = argparse.ArgumentParser(prog="read")
    with read_output_scope([], "projects.list"):
        parsed = parse_or_usage_error(parser, [], "read")
    assert parsed.full is False
    assert "--full" in parser.format_help()


def test_reply_budget_is_below_recorded_harness_caps():
    # Claude official tools reference: 30,000 characters by default.
    # Codex functions.exec documentation: 10,000 aggregate tokens by default.
    # UTF-8 bytes conservatively bound characters; bytes are not token estimates.
    assert REPLY_LIMIT_BYTES < 30_000
    assert REPLY_LIMIT_BYTES < 10_000


def test_reply_budget_counts_multibyte_utf8():
    from yoke_cli.transport.output_limit import reply_exceeds_limit

    assert not reply_exceeds_limit("é" * (REPLY_LIMIT_BYTES // 2))
    assert reply_exceeds_limit("é" * (REPLY_LIMIT_BYTES // 2 + 1))


def test_mutation_pointer_never_teaches_read_only_full_flag(capsys):
    raw = response("items.create", {"body": "x" * REPLY_LIMIT_BYTES})
    assert emit_response(raw, json_mode=True) == 0
    pointer = json.loads(capsys.readouterr().out)
    assert "already ran" in pointer["read"]
    assert "--full" not in pointer["read"]
    Path(pointer["saved_response"]).unlink()
