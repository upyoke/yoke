"""The one shell-command parse every Bash hook guard shares."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.hook_runner.local_privacy_guard import classify_shell_command
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_core.hooks.types import HookContext


def _argvs(command: str) -> list[tuple[str, ...]]:
    return [segment.argv for segment in parse_shell(command).segments]


def test_glued_semicolon_never_sticks_to_the_previous_word() -> None:
    assert _argvs("yoke --target-root /lane; git status") == [
        ("yoke", "--target-root", "/lane"),
        ("git", "status"),
    ]


def test_env_dash_i_and_underscore_assignments_leave_the_command_word() -> None:
    (segment,) = parse_shell("env -i _X=1 PYTHONPATH=/src pytest -q").segments
    assert segment.argv == ("pytest", "-q")
    assert segment.program == "pytest"
    assert segment.assignment("PYTHONPATH") == "/src"
    assert _argvs("env -u HOME -- ls") == [("ls",)]


def test_heredoc_body_with_guarded_words_is_input_not_commands() -> None:
    command = (
        "yoke items structured-field replace YOK-1 --field spec --stdin <<'EOF'\n"
        "Run pytest runtime/ tests/ ; rm -rf / && cd /tmp\n"
        "it's unbalanced \"quoting\n"
        "EOF\n"
        "echo done"
    )
    parsed = parse_shell(command)
    assert [segment.program for segment in parsed.segments] == ["yoke", "echo"]
    assert parsed.unparsed == ()
    assert parsed.heredocs[0].expands is False
    assert "pytest runtime/" in parsed.heredocs[0].body


def test_quoted_operators_stay_data_and_pipes_record_their_stage() -> None:
    parsed = parse_shell("rg 'a|pytest|b' file | head -5 && echo \"x;y\"")
    assert [(s.argv, s.pipeline, s.stage) for s in parsed.segments] == [
        (("rg", "a|pytest|b", "file"), 0, 0),
        (("head", "-5"), 0, 1),
        (("echo", "x;y"), 1, 0),
    ]


def test_compound_keywords_and_word_lists_are_not_commands() -> None:
    assert _argvs("for f in /a /b; do cat \"$f\"; done") == [(), ("cat", "$f"), ()]


def test_cd_after_an_earlier_command_moves_later_segments(tmp_path: Path) -> None:
    target = tmp_path / "ci"
    target.mkdir()
    parsed = parse_shell(
        f"yoke messages acknowledge M; mkdir -p {target} && cd {target} "
        "&& gh run view > job.log"
    )
    cwds = parsed.segment_cwds("/repo")
    assert cwds[:3] == ["/repo", "/repo", "/repo"]
    assert cwds[3] == str(target.resolve())


def test_unreadable_cd_makes_later_directories_unknown() -> None:
    parsed = parse_shell('cd "$WORK" && ls; cd /tmp && ls')
    assert parsed.segment_cwds("/repo") == ["/repo", "", "", str(Path("/tmp").resolve())]


def test_hook_context_parses_once_for_every_guard() -> None:
    context = HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload={"tool_input": {"command": "D=/tmp; ls $D"}},
    )
    assert context.shell is context.shell
    assert context.shell.segments[-1].argv == ("ls", "/tmp")


def test_privacy_resolves_dot_dot_against_the_in_command_cd(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = home / "repo"
    (repo / "docs").mkdir(parents=True)
    assert classify_shell_command("ls ..", home=home, cwd=str(repo)) is not None
    command = f"cd {repo / 'docs'} && ls .. && find .. -name x"
    assert classify_shell_command(command, home=home, cwd=str(repo)) is None
