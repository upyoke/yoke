"""Drive ``yoke setup --agent`` invocations in-process, with Apply faked."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from yoke_cli import main as yoke_operations_cli
from yoke_cli.commands.adapters import onboard_apply, onboard_interactive
from yoke_cli.config import (
    onboard_machine_setup,
    onboard_preflight,
    onboard_session_relay,
    onboard_wizard,
)
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow
from yoke_cli.config.onboard_wizard_path import PathFlow

MACHINE_ONLY_ANSWERS = (
    "project.mode=machine-only",
    "connect.destination=local",
    "connect.local_universe=fresh",
    "connect.admin_name=Test Person",
    "github.machine=skip",
)


class FakeApply:
    """Stands in for the durable-report Apply: previews a plan, records applies."""

    def __init__(self) -> None:
        self.applied: list[dict[str, Any]] = []
        self.options: list[dict[str, Any]] = []
        self.fail_next: Exception | None = None
        self.effects: Callable[[dict], None] | None = None

    def __call__(self, kwargs: dict, tui_progress=None, **options: Any) -> dict:
        if not kwargs.get("apply"):
            return {"plan": {"steps": [{"action": "register-machine", "target": ""}]}}
        self.applied.append(kwargs)
        self.options.append(options)
        if self.effects is not None:
            self.effects(kwargs)
        if self.fail_next is not None:
            failure, self.fail_next = self.fail_next, None
            raise failure
        return {
            "plan": {"steps": []},
            "apply_report": {"path": "/tmp/report.json", "status": "applied"},
            "install_health": {"ok": True, "checks": [{"name": "yoke", "ok": True}]},
        }


class AgentDriver:
    """One machine home, answered one ``yoke setup --agent`` call at a time."""

    def __init__(self, capsys) -> None:
        self._capsys = capsys
        self.stderr = ""

    def __call__(
        self, *answers: str, flags: tuple[str, ...] = ()
    ) -> tuple[int, list[dict]]:
        args = ["setup", "--agent", *flags]
        for answer in answers:
            args.extend(["--answer", answer])
        code = yoke_operations_cli.main(args)
        captured = self._capsys.readouterr()
        self.stderr = captured.err
        return code, [json.loads(line) for line in captured.out.splitlines() if line]

    def replayed(self, answer: str | None = None) -> dict:
        """Answer, then replay from the store alone: both stop at the same place.

        A question must come back unchanged from a bare call, which rebuilds
        the run from its stored answers and run facts. A browser step is the
        one outcome a bare call moves past, by checking the approval.
        """
        code, lines = self(*([answer] if answer else []))
        line = lines[-1]
        assert code == 0, (answer, line)
        assert line["state"] in {"question", "browser", "done"}, (answer, line)
        if line["state"] == "question":
            replay_code, replay = self()
            assert (replay_code, replay[-1]) == (code, line), (answer, replay[-1])
        return line

    def replay_each(self, answers: tuple[str, ...]) -> dict:
        """Start setup, then give each answer, replaying after every one."""
        line = self.replayed()
        for answer in answers:
            line = self.replayed(answer)
        return line

    def walk(self, answers: tuple[str, ...]) -> tuple[int, list[dict]]:
        result = self()
        for answer in answers:
            result = self(answer)
            assert result[0] == 0, result
        return result


def isolate_agent_setup(tmp_path: Path, monkeypatch) -> FakeApply:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(onboard_wizard, "is_interactive", lambda *_: False)
    monkeypatch.setattr(onboard_machine_setup, "prepare", lambda *_: None)
    monkeypatch.setattr(
        PathFlow,
        "_check_install",
        lambda _self: (
            {"login_verified": True, "login_resolved": {"yoke": "/tmp/bin/yoke"}},
            "",
        ),
    )
    monkeypatch.setattr(
        onboard_session_relay,
        "install",
        lambda **_k: onboard_session_relay.RelayInstallOutcome(
            installed=True, reused=False
        ),
    )
    monkeypatch.setattr(
        onboard_preflight,
        "preflight",
        lambda *_a, **_k: SimpleNamespace(problems=[], notes=[]),
    )
    monkeypatch.setattr(
        onboard_interactive, "finish_pending_source_install", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        BoardArtFlow, "_board_art_after_apply", lambda _self, _report: False
    )
    fake = FakeApply()
    monkeypatch.setattr(onboard_apply, "apply_with_durable_report", fake)
    return fake


def git_checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    return path


def fake_clone(parent, name: str, remote: str, **_kwargs: Any) -> None:
    """Clone stand-in: a git repo whose origin is ``remote``, carrying a Yoke layer."""
    root = Path(parent) / name
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", remote], check=True
    )
    (root / ".yoke").mkdir()
    (root / ".yoke" / "layer.md").write_text("installed layer\n")
