"""Execute glob repairs and compare the files they select."""

from pathlib import Path
import re
import subprocess
from unittest import mock

import pytest

from yoke_contracts.hook_runner.shell_guard_repairs import glob_repair
from yoke_core.domain import lint_unmatched_path_glob as core
from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob


@pytest.mark.parametrize("hook", ["core", "client"])
@pytest.mark.parametrize("invocation", ["rg -l needle", "ls"])
@pytest.mark.parametrize(
    "pattern, expected",
    [
        (".yoke/{install*,docs/index.md}", {"install.py", "docs/index.md"}),
        (".yoke/{install*,docs/{index,extra}.md}",
         {"install.py", "docs/index.md", "docs/extra.md"}),
        (".yoke/*/{index,extra}.md", {"docs/index.md", "docs/extra.md"}),
        (".yoke/install*.py", {"install.py"}),
    ],
)
def test_printed_repairs_select_intact_patterns(tmp_path: Path, hook, invocation, pattern, expected):
    tree = tmp_path / ".yoke"
    (tree / "docs").mkdir(parents=True)
    for name in ("install.py", "docs/index.md", "docs/extra.md", "docs/other.md"):
        (tree / name).write_text("needle\n")
    payload = {
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": f"{invocation} {pattern}", "shell": "/bin/zsh"},
    }
    # A star with matching files normally passes; exercise its repair directly.
    with mock.patch.object(core, "_read_mode", return_value="deny"):
        if "{" in pattern:
            reason = (core.evaluate_payload(payload)[1] if hook == "core"
                      else lint_unmatched_path_glob(payload).message)
            repaired = re.search(r"Repaired command: `([^`]+)`", reason)[1]
        else:
            repaired = glob_repair(payload["tool_input"]["command"], pattern,
                                   str(tmp_path))[0]
    result = subprocess.run(["sh", "-c", repaired], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert {str(Path(name).relative_to(".yoke"))
            for name in result.stdout.splitlines()} == expected


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
    with mock.patch.object(core, "_read_mode", return_value="deny"):
        reasons = [core.evaluate_payload(payload)[1],
                   lint_unmatched_path_glob(payload).message]
    for reason in reasons:
        assert "Repaired command:" not in reason
        assert "rg --files" in reason


def test_missing_root_has_no_repair(tmp_path: Path):
    assert glob_repair("rg needle absent/path*", "absent/path*", str(tmp_path)) is None
