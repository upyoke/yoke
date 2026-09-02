"""The unattended posture each harness needs, and the passes that write it.

Covers the two config surfaces Yoke edits in place — Codex's TOML and
Cursor's JSON — plus the pass that drives all three harnesses. The
invariants under test are the same for both surfaces: set what is absent,
never overwrite what the operator set, leave every unrelated setting alone,
and say out loud what changed.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from yoke_contracts.harness_unattended_posture import (
    CODEX_APPROVAL_POLICY_KEY,
    CODEX_SANDBOX_MODE_KEY,
    CURSOR_APPROVAL_MODE,
    CURSOR_APPROVAL_MODE_KEY,
    CURSOR_SANDBOX_CONTAINER,
    CURSOR_SANDBOX_MODE,
    CURSOR_SANDBOX_MODE_KEY,
    claude_posture_problems,
    codex_posture_problems,
    cursor_posture_problems,
    posture_problems,
)
from yoke_core.tools.install_yoke_launcher_codex import (
    configure_codex_unattended_posture,
)
from yoke_core.tools.install_yoke_launcher_codex_config import (
    CodexConfigUnreadable,
    changed,
    parse_config,
    plan,
)
from yoke_core.tools.install_yoke_launcher_cursor import (
    configure_cursor_unattended_posture,
)

CHECKOUT = "/repos/example"


def _codex_home(tmp_path: Path, text: str = "") -> Path:
    home = tmp_path / ".codex"
    home.mkdir()
    target = home / "config.toml"
    if text:
        target.write_text(text, encoding="utf-8")
    return target


def _cursor_home(tmp_path: Path, payload: dict | None = None) -> Path:
    home = tmp_path / ".cursor"
    home.mkdir()
    target = home / "cli-config.json"
    if payload is not None:
        target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_codex_plan_writes_both_keys_and_the_checkout_trust():
    text, record = plan("", CHECKOUT)
    parsed = parse_config(text)
    assert parsed[CODEX_APPROVAL_POLICY_KEY] == "never"
    assert parsed[CODEX_SANDBOX_MODE_KEY] == "danger-full-access"
    assert parsed["projects"][CHECKOUT]["trust_level"] == "trusted"
    assert record["conflicts"] == []


def test_codex_plan_preserves_every_unrelated_setting():
    base = (
        'model = "gpt"\n\n[hooks.state."/repo/.codex/hooks.json:Stop::0"]\n'
        'trusted_hash = "abc"\n'
    )
    text, _record = plan(base, CHECKOUT)
    parsed = parse_config(text)
    assert parsed["model"] == "gpt"
    assert parsed["hooks"]["state"]["/repo/.codex/hooks.json:Stop::0"] == {
        "trusted_hash": "abc"
    }


def test_codex_plan_is_idempotent():
    once, _ = plan("", CHECKOUT)
    twice, record = plan(once, CHECKOUT)
    assert twice == once
    assert not changed(record)


def test_codex_plan_never_overwrites_an_operator_choice():
    base = 'approval_policy = "on-request"\nsandbox_mode = "read-only"\n'
    text, record = plan(base, CHECKOUT)
    parsed = parse_config(text)
    assert parsed[CODEX_APPROVAL_POLICY_KEY] == "on-request"
    assert parsed[CODEX_SANDBOX_MODE_KEY] == "read-only"
    assert len(record["conflicts"]) == 2
    assert record["set_keys"] == []


def test_codex_plan_refuses_a_config_it_cannot_parse():
    with pytest.raises(CodexConfigUnreadable):
        plan("this is not = = toml", CHECKOUT)


def test_codex_pass_skips_a_machine_with_no_codex(tmp_path: Path):
    absent = tmp_path / "nothing" / "config.toml"
    assert configure_codex_unattended_posture(
        config_path=absent, stream=io.StringIO()
    ) == []


def test_codex_pass_writes_and_names_what_it_granted(tmp_path: Path):
    target = _codex_home(tmp_path)
    stream = io.StringIO()
    actions = configure_codex_unattended_posture(
        checkout=Path(CHECKOUT), config_path=target, stream=stream
    )
    assert len(actions) == 1
    assert "enabled unattended mode" in actions[0]
    assert codex_posture_problems(parse_config(target.read_text())) == ()
    assert actions[0] in stream.getvalue()


def test_codex_pass_reports_a_conflict_without_writing(tmp_path: Path):
    target = _codex_home(tmp_path, 'approval_policy = "untrusted"\n')
    actions = configure_codex_unattended_posture(
        config_path=target, stream=io.StringIO()
    )
    assert any("left your own setting in place" in line for line in actions)
    assert parse_config(target.read_text())[CODEX_APPROVAL_POLICY_KEY] == "untrusted"


def test_cursor_pass_sets_both_keys_and_keeps_the_rest(tmp_path: Path):
    target = _cursor_home(tmp_path, {"model": {"modelId": "grok"}, "hints": True})
    actions = configure_cursor_unattended_posture(
        config_path=target, stream=io.StringIO()
    )
    payload = json.loads(target.read_text())
    assert payload[CURSOR_APPROVAL_MODE_KEY] == CURSOR_APPROVAL_MODE
    assert payload[CURSOR_SANDBOX_CONTAINER][CURSOR_SANDBOX_MODE_KEY] == (
        CURSOR_SANDBOX_MODE
    )
    assert payload["model"] == {"modelId": "grok"}
    assert payload["hints"] is True
    assert len(actions) == 1
    assert cursor_posture_problems(payload) == ()


def test_cursor_pass_never_overwrites_an_operator_choice(tmp_path: Path):
    target = _cursor_home(
        tmp_path,
        {
            CURSOR_APPROVAL_MODE_KEY: "allowlist",
            CURSOR_SANDBOX_CONTAINER: {CURSOR_SANDBOX_MODE_KEY: "enabled"},
        },
    )
    actions = configure_cursor_unattended_posture(
        config_path=target, stream=io.StringIO()
    )
    payload = json.loads(target.read_text())
    assert payload[CURSOR_APPROVAL_MODE_KEY] == "allowlist"
    assert len(actions) == 2
    assert all("left your own setting in place" in line for line in actions)


def test_cursor_pass_skips_a_machine_with_no_cursor(tmp_path: Path):
    absent = tmp_path / "nothing" / "cli-config.json"
    assert configure_cursor_unattended_posture(
        config_path=absent, stream=io.StringIO()
    ) == []


def test_posture_readers_agree_with_the_dispatcher():
    codex = {"approval_policy": "never", "sandbox_mode": "danger-full-access"}
    cursor = {
        CURSOR_APPROVAL_MODE_KEY: CURSOR_APPROVAL_MODE,
        CURSOR_SANDBOX_CONTAINER: {CURSOR_SANDBOX_MODE_KEY: CURSOR_SANDBOX_MODE},
    }
    claude = {"preferences": {"bypassPermissionsModeEnabled": True}}
    assert posture_problems("codex", codex) == codex_posture_problems(codex) == ()
    assert posture_problems("cursor", cursor) == cursor_posture_problems(cursor) == ()
    assert posture_problems("claude-code", claude) == claude_posture_problems(claude)
    with pytest.raises(ValueError):
        posture_problems("emacs", {})


def test_claude_reader_names_a_prompting_preference():
    problems = claude_posture_problems({"preferences": {}})
    assert len(problems) == 1
    assert "bypassPermissionsModeEnabled" in problems[0]
