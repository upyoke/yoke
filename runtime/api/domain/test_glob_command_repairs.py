"""Parse repairs and enumerate their selected files without external tools."""

import glob
from pathlib import Path
import re
import shlex

import pytest

from yoke_contracts.hook_runner.shell_guard_repairs import (
    _brace_alternatives,
    glob_repair,
)
from yoke_core.domain import lint_unmatched_path_glob as core
from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob


def _selected_files(command: str, cwd: Path) -> set[Path]:
    """Validate the emitted argv and enumerate its anchored glob in Python."""
    words = shlex.split(command)
    if words[0] == "cd":
        assert words[2] == "&&"
        cwd = Path(words[1])
        words = words[3:]
    assert words[0] == "rg"
    assert words[1:-3] in (["--files"], ["-l", "needle"])
    assert words[-2] == "--glob"
    assert words[-1].startswith("/")
    root = (cwd / words[-3]).resolve()
    assert root.is_dir()
    selected = set()
    for pattern in _brace_alternatives(words[-1][1:]):
        for name in glob.glob(str(cwd / pattern), recursive=True):
            path = Path(name).resolve()
            assert path.is_relative_to(root)
            if path.is_file():
                selected.add(path)
    return selected


@pytest.mark.parametrize("hook", ["core", "client"])
@pytest.mark.parametrize("invocation", ["rg -l needle", "ls"])
@pytest.mark.parametrize(
    "pattern, expected",
    [
        (".yoke/{install*,docs/missing*.md}", {"install.py"}),
        (".yoke/{absent*,docs/{index,extra}.md}", {"docs/index.md", "docs/extra.md"}),
        (".yoke/*/{index,absent}.md", {"docs/index.md"}),
        (".yoke/install*.py", {"install.py"}),
    ],
)
def test_printed_repairs_select_intact_patterns(tmp_path, hook, invocation, pattern, expected):
    tree = tmp_path / ".yoke"
    (tree / "docs").mkdir(parents=True)
    for name in ("install.py", "docs/index.md", "docs/extra.md", "docs/other.md"):
        (tree / name).write_text("needle\n")
    payload = {
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": f"{invocation} {pattern}", "shell": "/bin/zsh"},
    }
    if "{" in pattern:
        reason = (core.evaluate_payload(payload)[0] if hook == "core"
                  else lint_unmatched_path_glob(payload).message)
        repaired = re.search(r"Repaired command: `([^`]+)`", reason)[1]
    else:
        repaired = glob_repair(payload["tool_input"]["command"], pattern,
                               str(tmp_path))[0]
    assert _selected_files(repaired, tmp_path) == {(tree / name).resolve() for name in expected}


@pytest.mark.parametrize(
    "command",
    [
        "rg needle docs/missing* > result.txt",
        "rg needle docs/missing* 2> 'errors with spaces'",
        "cd elsewhere && rg needle docs/missing*",
        "rg needle docs/missing* | sort",
        "rg needle docs/missing* docs/other*",
        "rg --glob '*.md' needle docs/missing*",
        "grep -v needle docs/missing*",
        "ls -l docs/missing*",
        "rg needle docs/{a..z}*",
        "rg needle docs/{a,b*",
        "rg needle docs/[broken*",
        "rg needle docs/missing***",
        "rg needle docs/missing* <<'EOF'\nbody\nEOF",
    ],
)
def test_unsafe_repairs_keep_manual_recipe(tmp_path: Path, command):
    (tmp_path / "docs").mkdir()
    payload = {"tool_name": "Bash", "cwd": str(tmp_path),
               "tool_input": {"command": command, "shell": "/bin/zsh"}}
    reasons = [core.evaluate_payload(payload)[0],
               lint_unmatched_path_glob(payload).message]
    for reason in reasons:
        assert "Repaired command:" not in reason
        assert "rg --files" in reason


def test_missing_root_has_no_repair(tmp_path: Path):
    assert glob_repair("rg needle absent/path*", "absent/path*", str(tmp_path)) is None


@pytest.mark.parametrize("root_name", ["home with spaces", "absolute-root"])
def test_external_search_root_does_not_include_nested_names(tmp_path: Path, root_name):
    tree = tmp_path / root_name
    (tree / "nested").mkdir(parents=True)
    target = tree / "Meeting.txt"
    target.write_text("needle\n")
    (tree / "nested" / "Meeting.txt").write_text("needle\n")
    cwd = tmp_path / "repository"
    cwd.mkdir()
    token = str(tree / "Meeting*")
    repaired = glob_repair(f"rg -l needle '{token}'", token, str(cwd))[0]
    assert _selected_files(repaired, cwd) == {target.resolve()}


@pytest.mark.parametrize("hook", ["core", "client"])
@pytest.mark.parametrize("missing", ["none", "some", "all"])
@pytest.mark.parametrize("pattern", ["docs/{a*,b*}.md", "docs/{a*,{b*,c*}}.md"])
def test_brace_matching_checks_each_expanded_operand(tmp_path, hook, missing, pattern):
    docs = tmp_path / "docs"
    docs.mkdir()
    if missing != "all":
        (docs / "alpha.md").write_text("a")
    if missing == "none":
        (docs / "beta.md").write_text("b")
        (docs / "charlie.md").write_text("c")
    payload = {"tool_name": "Bash", "cwd": str(tmp_path),
               "tool_input": {"command": f"ls {pattern}", "shell": "/bin/zsh"}}
    denied = (core.evaluate_payload(payload) is not None if hook == "core"
              else lint_unmatched_path_glob(payload).outcome == "deny")
    assert denied is (missing != "none")


def test_nested_brace_expansion_retains_whole_paths():
    assert set(_brace_alternatives(".yoke/{install*,docs/{index,other}.md}")) == {
        ".yoke/install*", ".yoke/docs/index.md", ".yoke/docs/other.md",
    }
