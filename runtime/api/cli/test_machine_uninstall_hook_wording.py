"""Machine uninstall says whether a harness settings file survived."""

import json

from yoke_cli.config import machine_uninstall_steps as steps
from yoke_harness.hooks.machine_hooks import ensure_machine_hooks


def test_stripping_hooks_from_a_preexisting_file_says_the_file_is_kept(tmp_path):
    claude_home = tmp_path / "harness-home" / ".claude"  # the conftest-isolated home
    claude_home.mkdir(parents=True)
    settings = claude_home / "settings.json"
    settings.write_text(json.dumps({"model": "opus"}))
    ensure_machine_hooks(["claude-code"])
    assert "hooks" in json.loads(settings.read_text())

    output: list[str] = []
    steps._remove_machine_hooks(output.append)

    [line] = output
    assert f"claude-code: removed Yoke hooks from {settings} (file kept)" in line
    assert f"claude-code: removed {settings};" not in line
    assert json.loads(settings.read_text())["model"] == "opus"
