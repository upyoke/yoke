"""Complete machine/write delivery and atomic human-read safety net."""

import json

import pytest

from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
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


@pytest.mark.parametrize("function", ["events.emit", "organizations.create", "test_machine.reset"])
def test_side_effecting_functions_are_not_reads(function):
    assert function not in registered_read_ids()
    assert function not in READ_FUNCTION_IDS


def test_pure_items_get_is_a_read():
    assert "items.get.run" in registered_read_ids()
    assert "items.get.run" in READ_FUNCTION_IDS


@pytest.mark.parametrize("function", ["events.emit", "organizations.create", "test_machine.reset"])
def test_write_help_does_not_add_read_full_option(function):
    import argparse
    from yoke_cli.commands._helpers import parse_or_usage_error

    parser = argparse.ArgumentParser(prog="write")
    with read_output_scope([], function):
        parse_or_usage_error(parser, [], "write")
    assert "--full" not in parser.format_help()


@pytest.mark.parametrize("size", [4_001, 28_001, 80_000])
@pytest.mark.parametrize("function", ["qa.plan.list", "items.create"])
def test_json_always_returns_complete_envelope(capsys, size, function):
    raw = response(function, {"body": "x" * size})
    assert emit_response(raw, json_mode=True) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["result"] == raw.result
    assert "saved_response" not in rendered


@pytest.mark.parametrize(
    "function", ["items.create", "events.emit", "organizations.create", "test_machine.reset"]
)
def test_human_write_is_always_complete(capsys, function):
    value = "m" * (REPLY_LIMIT_BYTES + 1)
    assert emit_response(response(function, {"body": value}), json_mode=False) == 0
    assert value in capsys.readouterr().out


def test_large_human_read_refuses_without_partial_answer(capsys):
    import argparse
    from yoke_cli.commands._helpers import parse_or_usage_error

    raw = response(result={"body": "marker" * REPLY_LIMIT_BYTES})
    with read_output_scope([], "qa.plan.list"):
        parse_or_usage_error(argparse.ArgumentParser(prog="read"), [], "read")
        assert emit_response(raw, json_mode=False) == 1
    out = capsys.readouterr()
    assert "marker" not in out.out
    assert "read_output_limit_exceeded" in out.err
    assert "28000" in out.err
    assert "--full" in out.err


@pytest.mark.parametrize("scope", [False, True])
def test_full_returns_whole_human_read(capsys, scope):
    value = "z" * (REPLY_LIMIT_BYTES + 1)
    with read_output_scope(["--full"] if scope else []):
        assert emit_response(response(result={"body": value}), json_mode=False, full=not scope) == 0
    assert value in capsys.readouterr().out


def test_full_does_not_escape_its_invocation():
    from yoke_cli.transport.output_limit import full_output_requested

    with read_output_scope(["--full"]):
        assert full_output_requested()
    assert not full_output_requested()
    with read_output_scope(["--", "--full"]):
        assert not full_output_requested()


def test_combined_streams_count_utf8_bytes(capsys):
    def writer(raw, stdout, stderr):
        stdout.write("partial")
        stderr.write("é" * 14_000)

    assert emit_response(response(), json_mode=False, human_writer=writer) == 1
    out = capsys.readouterr()
    assert "partial" not in out.out
    assert "read_output_limit_exceeded" in out.err


def test_registered_read_help_teaches_full_without_requesting_it():
    import argparse
    from yoke_cli.commands._helpers import parse_or_usage_error

    parser = argparse.ArgumentParser(prog="read")
    with read_output_scope([], "projects.list"):
        parsed = parse_or_usage_error(parser, [], "read")
    assert parsed.full is False
    assert "--full" in parser.format_help()


def _read_hint(function, configure):
    import argparse
    from yoke_cli.commands._helpers import parse_or_usage_error
    from yoke_cli.transport.output_limit import read_recovery

    parser = argparse.ArgumentParser(prog="read")
    configure(parser)
    with read_output_scope([], function):
        parse_or_usage_error(parser, [], "read")
        return read_recovery(function)


def test_hint_names_only_flags_the_command_has():
    def configure(parser):
        parser.add_argument("--deployment-run-id")
        parser.add_argument("--item", action="append")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--json", action="store_true")

    hint = _read_hint("qa.activity.list", configure)
    assert hint.startswith(
        "Narrow yoke qa activity list with its fields --section; filters "
        "--deployment-run-id, --item; limit --limit;"
    )
    assert "FIELD" not in hint
    assert "--json" not in hint
    assert hint.endswith("or add --full to request the entire answer explicitly.")


def test_hint_names_field_and_paging_flags_when_present():
    def configure(parser):
        parser.add_argument("fields", nargs="*", metavar="FIELD")
        parser.add_argument("--section")
        parser.add_argument("--cursor")

    hint = _read_hint("items.get.run", configure)
    assert "Narrow yoke items get with its fields FIELD, --section; paging --cursor;" in hint


def test_read_without_its_own_narrowing_flags_names_the_shared_section():
    hint = _read_hint("sessions.identity", lambda parser: None)
    assert hint.startswith("Narrow yoke sessions identity with its fields --section;")
    assert "--full" in hint


def test_hint_without_recorded_parser_points_at_help():
    from yoke_cli.transport.output_limit import read_recovery

    with read_output_scope([], "qa.activity.list"):
        hint = read_recovery("qa.activity.list")
    assert hint == "Run yoke qa activity list --help to find how to narrow this read."


def test_safety_net_below_character_cap():
    assert REPLY_LIMIT_BYTES == 28_000
    assert REPLY_LIMIT_BYTES < 30_000
