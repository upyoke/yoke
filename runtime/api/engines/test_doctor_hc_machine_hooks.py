"""Doctor reports each installed harness's machine-wide hooks."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_hc_machine_hooks import hc_machine_hooks
from yoke_harness.hooks.machine_hooks import ensure_machine_hooks


class _Records:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def record(self, name: str, desc: str, status: str, detail: str) -> None:
        self.rows.append((name, desc, status, detail))


def _home(tmp_path: Path) -> Path:
    return tmp_path / "harness-home"  # the conftest-isolated home


def _run() -> tuple[str, str]:
    records = _Records()
    hc_machine_hooks(None, None, records)
    [(name, _, status, detail)] = records.rows
    assert name == "HC-machine-hooks"
    return status, detail


def test_no_installed_harness_passes(tmp_path):
    assert _run() == ("PASS", "no supported harness is installed")


def test_installed_hooks_pass_with_one_line_per_harness(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    ensure_machine_hooks()
    status, detail = _run()
    assert status == "PASS"
    assert "claude-code: installed" in detail and "cursor: installed" in detail


def test_missing_hooks_warn_with_the_setup_step(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    status, detail = _run()
    assert status == "WARN"
    assert "claude-code: missing" in detail and "yoke setup" in detail


def test_malformed_config_fails_with_recovery(tmp_path):
    claude = _home(tmp_path) / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text("{broken")
    status, detail = _run()
    assert status == "FAIL"
    assert "claude-code: malformed" in detail
    assert "fix or move the file, then run `yoke setup` again" in detail


def test_untrusted_codex_hooks_warn(tmp_path):
    codex = _home(tmp_path) / ".codex"
    codex.mkdir(parents=True)
    ensure_machine_hooks(["codex"])
    (codex / "config.toml").write_text("")
    status, detail = _run()
    assert status == "WARN"
    assert "codex: untrusted" in detail
