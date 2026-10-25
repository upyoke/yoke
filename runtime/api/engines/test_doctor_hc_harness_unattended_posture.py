"""The health check that reports whether any harness still prompts on yoke.

Three outcomes matter and are distinct: a machine with no harness at all is
N/A (nothing to judge), a harness whose config still prompts is FAIL and
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
    claude_settings_path,
    managed_config_paths,
)
from yoke_core.engines.doctor_hc_harness_unattended_posture import (
    SLUG,
    hc_harness_unattended_posture,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines import doctor_hc_harness_unattended_posture as mod

UNATTENDED_CODEX = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'


def _paths(
    tmp_path: Path, monkeypatch, *, codex=None, cursor=None, claude=None, cli=None
):
    """Point the check at a temp home, creating only the config given."""
    monkeypatch.setattr(mod, "resolve_harness_clis", lambda path: [])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    resolved = managed_config_paths()
    for target, payload in (
        (resolved["codex"], codex),
        (resolved["cursor"], cursor),
        (resolved["claude-code"], claude),
        (claude_settings_path(), cli),
    ):
        if payload is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
    return resolved


def _run():
    records = RecordCollector()
    hc_harness_unattended_posture(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def _status(result) -> str:
    return result.result


def _detail(result) -> str:
    return f"{result.check_id} {result.check_name} {result.detail}"


def test_no_harness_on_the_machine_is_not_applicable(
    tmp_path: Path, monkeypatch
) -> None:
    _paths(tmp_path, monkeypatch)
    result = _run()
    assert _status(result) == "N/A"
    assert SLUG in _detail(result)


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
        cli=json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}),
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
    assert _status(result) == "FAIL"
    assert "does not parse" in _detail(result)


def test_installed_harness_without_posture_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace

    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        mod,
        "resolve_harness_clis",
        lambda path: [SimpleNamespace(harness_id="codex", path="codex")],
    )
    result = _run()
    assert result.result == "FAIL"
    assert "HARNESS_POSTURE_UNVERIFIED" in result.detail


def test_prompting_mode_fails_even_with_a_command_allow_entry(
    tmp_path: Path, monkeypatch
) -> None:
    _paths(
        tmp_path,
        monkeypatch,
        cursor=json.dumps(
            {
                CURSOR_APPROVAL_MODE_KEY: "allowlist",
                "permissions": {"allow": ["Shell(yoke *)"], "deny": []},
            }
        ),
    )
    result = _run()
    assert _status(result) == "FAIL"
    assert "approvalMode" in _detail(result)
    assert "doctor run --only harness-setup --fix" in _detail(result)


def test_prompting_mode_fails_naming_the_setting(tmp_path: Path, monkeypatch) -> None:
    _paths(
        tmp_path,
        monkeypatch,
        cli=json.dumps({"permissions": {"defaultMode": "auto", "allow": ["Bash(ls)"]}}),
    )
    result = _run()
    assert _status(result) == "FAIL"
    assert "permissions.defaultMode" in _detail(result)
    assert "doctor run --only harness-setup --fix" in _detail(result)


def test_an_unnamed_surface_labels_a_settings_problem_with_the_settings_file(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = _paths(
        tmp_path,
        monkeypatch,
        claude=json.dumps({"preferences": {CLAUDE_BYPASS_KEY: True}}),
        cli=json.dumps({"permissions": {"defaultMode": "auto"}}),
    )

    verdict, detail = mod.inspect_unattended_posture("claude-code", installed=True)

    assert verdict == "FAIL"
    assert f"{claude_settings_path()}: permissions.defaultMode is 'auto'" in detail
    assert str(resolved["claude-code"]) not in detail
