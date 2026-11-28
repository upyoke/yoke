"""Project and machine hook fixtures for the machine-hook dedup tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain.agents_render_hooks import (
    render_claude_hooks_block,
    render_codex_hooks_block,
    render_cursor_hooks_block,
)


def native_windows(monkeypatch) -> None:
    """Native Windows as the launchability check sees it: no ``/bin/sh``.

    Only the check's own module sees ``nt``, so pathlib in this process keeps
    its POSIX paths; ``yoke`` resolves the way ``yoke.cmd`` does on PATH.
    """
    from yoke_contracts import hook_shell_command as shell

    monkeypatch.setattr(shell, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        shell,
        "shutil",
        SimpleNamespace(which=lambda name: name if name == "yoke" else None),
    )


def yoke_on_path(monkeypatch) -> None:
    """``yoke`` starts wherever these tests run, as it does where setup ran."""
    from yoke_contracts import hook_shell_command as shell

    monkeypatch.setattr(
        shell,
        "shutil",
        SimpleNamespace(
            which=lambda name: name if name == "yoke" else shutil.which(name)
        ),
    )


_BUNDLE_KEY = {
    "claude-code": "claude_settings_hooks",
    "codex": "codex_hooks",
    "cursor": "cursor_hooks",
}


def write_project(root: Path, harness_id: str, *, native: bool = True) -> None:
    """The project render for one harness, as project install writes it here.

    ``native`` selects this host's command form the way install does; without
    it the file keeps the server's POSIX form, as a tracked render does.
    """
    from yoke_cli.project_install.hook_platform import native_bundle_hooks

    hooks = {
        "claude-code": render_claude_hooks_block,
        "codex": render_codex_hooks_block,
        "cursor": lambda: render_cursor_hooks_block()["hooks"],
    }[harness_id]()
    if native:
        key = _BUNDLE_KEY[harness_id]
        hooks = native_bundle_hooks({"hooks": {key: hooks}})["hooks"][key]
    path = root / {
        "claude-code": ".claude/settings.json",
        "codex": ".codex/hooks.json",
        "cursor": ".cursor/hooks.json",
    }[harness_id]
    document = {"hooks": hooks}
    if harness_id == "cursor":
        document = {"version": 1, "hooks": hooks}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def environment(harness_id: str, root: Path) -> dict[str, str]:
    owner = {
        "claude-code": "claude-user",
        "codex": "codex-user",
        "cursor": "cursor-user",
    }
    env = {"YOKE_HOOK_CONFIG_OWNER": owner[harness_id], "HOME": str(root / "home")}
    if harness_id == "claude-code":
        env["CLAUDE_PROJECT_DIR"] = str(root)
    if harness_id == "cursor":
        env["CURSOR_PROJECT_DIR"] = str(root)
    return env


def payload(harness_id: str, root: Path) -> str:
    if harness_id == "cursor":
        return json.dumps(
            {"session_id": "c-1", "conversation_id": "c-1", "cwd": str(root)}
        )
    return json.dumps({"session_id": "s-1", "cwd": str(root)})
