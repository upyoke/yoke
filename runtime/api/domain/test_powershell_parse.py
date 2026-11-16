"""The PowerShell tokenizer yields the segments the Bash guards already read."""

from __future__ import annotations

import pytest

from pathlib import Path

from yoke_contracts.hook_runner.powershell_parse import parse_powershell
from yoke_contracts.hook_runner.shell_parse import cd_destination, parse_for_shell

pytestmark = pytest.mark.windows


def _argvs(command: str) -> list[tuple[str, ...]]:
    return [segment.argv for segment in parse_powershell(command).segments]


def test_statements_split_on_semicolon_newline_and_chain_operators() -> None:
    assert _argvs("git status; git add -A\ngit commit -m 'x y' && git push || echo no") == [
        ("git", "status"),
        ("git", "add", "-A"),
        ("git", "commit", "-m", "x y"),
        ("git", "push"),
        ("echo", "no"),
    ]


def test_pipeline_stages_record_their_positions() -> None:
    parsed = parse_powershell("Get-ChildItem | Select-Object -First 3")
    assert [(s.pipeline, s.stage) for s in parsed.segments] == [(0, 0), (0, 1)]
    assert [s.program for s in parsed.segments] == ["get-childitem", "select-object"]


def test_call_operator_and_windows_path_name_the_program() -> None:
    (segment,) = parse_powershell(
        "& 'C:\\Program Files\\Yoke\\Yoke.EXE' items get YOK-1"
    ).segments
    assert segment.argv[1:] == ("items", "get", "YOK-1")
    assert segment.program == "yoke"


def test_quotes_and_backtick_escapes_are_removed() -> None:
    command = "git commit -m \"a `\"b`\" \"\"c\"\"\" -m 'it''s' `$HOME"
    (segment,) = parse_powershell(command).segments
    assert segment.argv == ("git", "commit", "-m", 'a "b" "c"', "-m", "it's", "$HOME")


def test_script_block_bodies_are_their_own_segments() -> None:
    command = "if ($dirty) { git stash push -m wip } else { Remove-Item -Recurse .\\x }"
    programs = [s.program for s in parse_powershell(command).segments if s.argv]
    assert programs == ["git", "remove-item"]
    loop = parse_powershell("Get-ChildItem | ForEach-Object { Remove-Item $_ }")
    assert loop.segments[-1].argv == ("Remove-Item", "$_")


def test_subexpressions_and_hashtables_stay_one_word() -> None:
    (segment,) = parse_powershell("yoke say $(Get-Date; 'x | y') @{a=1; b=2}").segments
    assert segment.argv == ("yoke", "say", "$(Get-Date; 'x | y')", "@{a=1; b=2}")


def test_assignments_record_values_or_run_the_command_on_the_right() -> None:
    value, command = parse_powershell("$env:PYTHONPATH = 'src'\n$sha = git rev-parse HEAD").segments
    assert value.argv == () and value.assignment("PYTHONPATH") == "src"
    assert command.argv == ("git", "rev-parse", "HEAD")


def test_here_string_body_is_input_not_commands() -> None:
    parsed = parse_powershell(
        "$spec = @'\ngit push --force; Remove-Item -Recurse C:\\\n'@\nyoke items update YOK-1 --stdin"
    )
    assert [s.program for s in parsed.segments if s.argv] == ["yoke"]
    (heredoc,) = parsed.heredocs
    assert heredoc.body == "git push --force; Remove-Item -Recurse C:\\"
    assert heredoc.expands is False
    assert parse_powershell('@"\n$x\n"@ | Out-File a.txt').heredocs[0].expands is True


def test_comments_are_dropped_and_redirects_kept() -> None:
    assert _argvs("<# block\ncomment #> yoke status 2>&1 > out.txt # trailing") == [
        ("yoke", "status", "2>&1", ">", "out.txt")
    ]


def test_trailing_ampersand_runs_in_the_background() -> None:
    assert _argvs("python -c 'print(1)' & git status") == [
        ("python", "-c", "print(1)"),
        ("git", "status"),
    ]


def test_backtick_newline_continues_the_line() -> None:
    assert _argvs("git commit `\n  -m done") == [("git", "commit", "-m", "done")]


def test_unbalanced_quote_is_unparsed_not_a_crash() -> None:
    parsed = parse_powershell("Write-Output ok; echo \"unterminated")
    assert [s.argv for s in parsed.segments] == [("Write-Output", "ok")]
    assert parsed.unparsed == ('echo "unterminated',)


def test_set_location_moves_later_segments() -> None:
    parsed = parse_powershell("Set-Location -Path /lane; sl sub; git status")
    assert cd_destination(parsed.segments[0].argv) == "/lane"
    lane = Path("/lane").resolve()
    assert parsed.segment_cwds("/main")[1:] == [str(lane), str(lane / "sub")]


def test_parse_for_shell_dispatches_and_bash_keeps_its_parser() -> None:
    assert parse_for_shell("echo `date`", "bash").shell == "bash"
    assert parse_for_shell("echo `$HOME", "powershell").segments[0].argv == ("echo", "$HOME")
    try:
        parse_for_shell("ls", "fish")
    except ValueError as exc:
        assert "harness_shell_tools" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown shell kind must refuse")
