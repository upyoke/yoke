"""Every registered read has atomic refusal and usable whole-answer retries."""

import shlex

from runtime.api.cli.registered_read_scale_test_support import command_for, parser_for
from yoke_cli.transport.output_limit import (
    REPLY_LIMIT_BYTES,
    read_output_scope,
    record_read_parser,
    record_read_section,
)
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.registered_reads import READ_FUNCTION_IDS


def test_headingless_read_refusals_have_exact_recovery(capsys):
    for function in sorted(READ_FUNCTION_IDS):
        try:
            assert_read_recovery(function, capsys)
        except AssertionError as exc:
            raise AssertionError(f"{function}: {exc}") from exc


def assert_read_recovery(function, capsys):
    command = command_for(function)
    route, adapter = command if command else (tuple(function.split(".")), None)
    parser = parser_for(function, adapter, route) if adapter else None
    capsys.readouterr()
    invocation = ("yoke", *route)
    with read_output_scope([], function, invocation):
        if parser:
            record_read_parser(parser)
            if any(a.dest == "read_section" for a in parser._actions):
                record_read_section(None)
        response = FunctionCallResponse(
            function=function,
            version="v1",
            success=True,
            result={"body": "unprinted-marker" * REPLY_LIMIT_BYTES},
        )
        assert emit_response(response, json_mode=False) == 1
    rendered = capsys.readouterr()
    assert rendered.out == ""
    assert "unprinted-marker" not in rendered.err
    assert "read_output_limit_exceeded" in rendered.err
    assert f"{shlex.join(invocation)} --full" in rendered.err
    assert f"{shlex.join(invocation)} --json" in rendered.err
    # A command-owned section is a real projection. The shared Markdown
    # section option cannot narrow this headingless reply and must be absent.
    own_section = parser and any(
        "--section" in a.option_strings and a.dest != "read_section"
        for a in parser._actions
    )
    if not own_section:
        assert "--section" not in rendered.err
