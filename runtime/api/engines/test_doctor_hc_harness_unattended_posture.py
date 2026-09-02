"""The health check that reports whether any harness still prompts on yoke.

Three outcomes matter and are distinct: a machine with no harness at all is
SKIP (nothing to judge), a harness whose config still prompts is FAIL and
names both the key and the repair, and a fully configured machine is PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.harness_unattended_posture import (
    CLAUDE_BYPASS_KEY,
    CURSOR_APPROVAL_MODE,
    CURSOR_APPROVAL_MODE_KEY,
    CURSOR_SANDBOX_CONTAINER,
    CURSOR_SANDBOX_MODE,
    CURSOR_SANDBOX_MODE_KEY,
)
from yoke_core.engines.doctor_hc_harness_unattended_posture import (
    SLUG,
    hc_harness_unattended_posture,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines import doctor_hc_harness_unattended_posture as mod

UNATTENDED_CODEX = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'


def _paths(tmp_path: Path, monkeypatch, *, codex=None, cursor=None, claude=None):
    """Point the check at temp config files, creating only what is given."""
    resolved = {}
    for harness, name, payload in (
        ("codex", "codex/config.toml", codex),
        ("cursor", "cursor/cli-config.json", cursor),
        ("claude-code", "claude/claude_desktop_config.json", claude),
    ):
        target = tmp_path / name
        if payload is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
        resolved[harness] = target
    monkeypatch.setattr(mod, "managed_config_paths", lambda: resolved)
    return resolved


def _run() -> tuple:
    records = RecordCollector()
    hc_harness_unattended_posture(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def _status(result) -> str:
    return next(
        value for value in result if value in ("PASS", "FAIL", "WARN", "SKIP")
    )


def _detail(result) -> str:
    return " ".join(str(value) for value in result)


def test_no_harness_on_the_machine_skips(tmp_path: Path, monkeypatch) -> None:
    _paths(tmp_path, monkeypatch)
    result = _run()
    assert _status(result) == "SKIP"
    assert SLUG in _detail(result)


def test_a_prompting_codex_fails_and_names_the_repair(
    tmp_path: Path, monkeypatch
) -> None:
    _paths(tmp_path, monkeypatch, codex='approval_policy = "on-request"\n')
    result = _run()
    detail = _detail(result)
    assert _status(result) == "FAIL"
    assert "approval_policy" in detail
    assert "install_yoke_launcher --repair" in detail


def test_a_prompting_cursor_fails(tmp_path: Path, monkeypatch) -> None:
    _paths(
        tmp_path,
        monkeypatch,
        cursor=json.dumps({CURSOR_APPROVAL_MODE_KEY: "allowlist"}),
    )
    result = _run()
    assert _status(result) == "FAIL"
    assert CURSOR_APPROVAL_MODE_KEY in _detail(result)


def test_every_configured_harness_passes(tmp_path: Path, monkeypatch) -> None:
    _paths(
        tmp_path,
        monkeypatch,
        codex=UNATTENDED_CODEX,
        cursor=json.dumps(
            {
                CURSOR_APPROVAL_MODE_KEY: CURSOR_APPROVAL_MODE,
                CURSOR_SANDBOX_CONTAINER: {
                    CURSOR_SANDBOX_MODE_KEY: CURSOR_SANDBOX_MODE
                },
            }
        ),
        claude=json.dumps({"preferences": {CLAUDE_BYPASS_KEY: True}}),
    )
    result = _run()
    detail = _detail(result)
    assert _status(result) == "PASS"
    assert "codex" in detail and "cursor" in detail


def test_an_unparseable_config_is_not_counted_as_configured(
    tmp_path: Path, monkeypatch
) -> None:
    """A file that does not parse teaches nothing, so it cannot read as PASS."""
    _paths(tmp_path, monkeypatch, codex="this is not = = toml")
    result = _run()
    assert _status(result) == "SKIP"
    assert "does not parse" in _detail(result)
