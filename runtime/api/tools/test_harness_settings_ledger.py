"""Uninstall reverts exactly the harness settings Yoke recorded writing.

Each case writes through the real installer pass, then reverts from the
record: the harness config must return to what the operator had, a value the
operator changed since must survive, and a second revert must be a no-op.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.claude_posture_install import configure_claude_cli_permission_mode
from yoke_contracts.codex_posture_install import configure_codex_unattended_posture
from yoke_contracts.cursor_posture_install import configure_cursor_unattended_posture
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_contracts.harness_settings_revert import revert_recorded

OPERATOR_CODEX = '# mine\nmodel = "o5"\n\n[profiles.fast]\nmodel = "o5-mini"\n'


def _home(tmp_path: Path, name: str, file: str, text: str | None) -> Path:
    (tmp_path / name).mkdir()
    target = tmp_path / name / file
    if text is not None:
        target.write_text(text, encoding="utf-8")
    return target


def test_codex_posture_and_trust_revert_to_the_operator_text(tmp_path):
    config = _home(tmp_path, ".codex", "config.toml", OPERATOR_CODEX)
    configure_codex_unattended_posture(checkout=Path("/repos/app"), config_path=config)
    assert config.read_text() != OPERATOR_CODEX
    assert [e["kind"] for e in ledger.read()] == [
        "codex_key",
        "codex_key",
        "codex_trust",
    ]
    lines, failures = revert_recorded()
    assert not failures and len(lines) == 3
    assert config.read_text() == OPERATOR_CODEX
    assert revert_recorded() == ([], [])


def test_a_value_the_operator_changed_is_left_in_place(tmp_path):
    config = _home(tmp_path, ".cursor", "cli-config.json", '{"model": "x"}')
    configure_cursor_unattended_posture(config_path=config)
    payload = json.loads(config.read_text())
    payload["approvalMode"] = "ask"
    config.write_text(json.dumps(payload))
    lines, failures = revert_recorded()
    assert not failures
    assert any(
        line.startswith("left your setting in place: approvalMode") for line in lines
    )
    assert json.loads(config.read_text()) == {"model": "x", "approvalMode": "ask"}


def test_claude_cli_mode_and_its_created_container_are_removed(tmp_path):
    settings = _home(tmp_path, ".claude", "settings.json", '{"theme": "dark"}')
    configure_claude_cli_permission_mode(settings_path=settings, stream=io.StringIO())
    assert "permissions" in json.loads(settings.read_text())
    revert_recorded()
    assert json.loads(settings.read_text()) == {"theme": "dark"}


def test_folder_trust_in_every_harness_is_revoked(tmp_path):
    claude = _home(tmp_path, "claude", "state.json", '{"projects": {}}')
    codex = _home(tmp_path, ".codex", "config.toml", OPERATOR_CODEX)
    cursor = tmp_path / "cursor" / "projects" / "app" / ".workspace-trusted"
    cursor.parent.parent.mkdir(parents=True)
    granted = grant_folder_trust(
        "/repos/app", claude_state=claude, codex_config=codex, cursor_file=cursor
    )
    assert len(granted) >= 3 and cursor.is_file()
    lines, failures = revert_recorded()
    assert not failures
    assert json.loads(claude.read_text()) == {"projects": {}}
    assert "/repos/app" not in codex.read_text()
    assert not cursor.exists()


def test_unreadable_record_is_a_named_failure(tmp_path):
    ledger.ledger_path().parent.mkdir(parents=True)
    ledger.ledger_path().write_text("{broken")
    lines, failures = revert_recorded()
    assert lines == [] and "could not be read" in failures[0]


def test_record_is_deduplicated_and_reports_an_unwritable_home(tmp_path, monkeypatch):
    entry = ledger.created_file_entry(tmp_path / "f")
    assert ledger.record(entry) is None and ledger.record(entry) is None
    assert ledger.read() == [entry]
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a directory")
    monkeypatch.setattr(ledger, "ledger_path", lambda: blocked / "ledger.json")
    report = ledger.record(entry)
    assert report and "yoke uninstall will not revert" in report
