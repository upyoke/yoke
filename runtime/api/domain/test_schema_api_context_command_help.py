"""Interpreter-isolated command-help introspection regressions."""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def _completed(command: list[str], returncode: int, output: str):
    return sac.subprocess.CompletedProcess(
        command,
        returncode,
        stdout=output if returncode == 0 else "",
        stderr=output if returncode != 0 else "",
    )


def test_command_help_uses_active_python_interpreter(monkeypatch) -> None:
    captured: list[list[str]] = []

    def _run(command, **_kwargs):
        captured.append(command)
        return _completed(command, 0, "Usage: example")

    monkeypatch.setattr(sac.subprocess, "run", _run)

    assert sac._try_help("example.module") == "Usage: example"
    assert captured == [[sac.sys.executable, "-m", "example.module", "--help"]]


def test_command_help_rejects_interpreter_bootstrap_errors(monkeypatch) -> None:
    def _run(command, **_kwargs):
        return _completed(
            command,
            1,
            "Error while finding module specification: ModuleNotFoundError",
        )

    monkeypatch.setattr(sac.subprocess, "run", _run)

    assert sac._try_help("missing.module") is None


def test_command_help_accepts_nonzero_usage_banner(monkeypatch) -> None:
    def _run(command, **_kwargs):
        return _completed(command, 2, "Usage: example <subcommand>")

    monkeypatch.setattr(sac.subprocess, "run", _run)

    assert sac._try_help("example.module") == "Usage: example <subcommand>"
