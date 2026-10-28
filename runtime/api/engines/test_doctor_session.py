"""Session readiness checks judge only the harness this session runs.

A machine can carry several harnesses. Before onboarding, the question is
whether *this* session can do Yoke work, so a signed-out or prompting harness
the session does not run must never fail it, and an unregistered session
must say its harness is unknown rather than guess one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_contracts.harness_unattended_posture import (
    CURSOR_APPROVAL_MODE,
    CURSOR_SANDBOX_MODE,
    claude_settings_path,
    managed_config_paths,
)
from yoke_core.engines import doctor_install
from yoke_core.engines import doctor_session as checks
from yoke_harness.hooks.session_permission_mode import capture_permission_mode
from yoke_core.engines.doctor_applicability_declarations import local_runtime_slugs
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

UNATTENDED_CODEX = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
SESSION = "11111111-1111-4111-8111-111111111111"


def run(fn, **kwargs):
    rec = RecordCollector()
    fn(None, DoctorArgs(project="42", **kwargs), rec)
    assert len(rec.results) == 1
    return rec.results[0]


def registered_as(
    monkeypatch, executor: str | None, surface: str | None = None
) -> None:
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id=SESSION)
    )
    identity = {
        "session_id": SESSION if executor else "other",
        "executor": executor,
        "executor_surface": surface
        or (harness_cli_manifest(executor).surface_id if executor else None),
    }
    monkeypatch.setattr(checks, "relay", lambda *a: identity)


def clis(monkeypatch, *harness_ids: str) -> None:
    monkeypatch.setattr(
        doctor_install,
        "resolve_harness_clis",
        lambda path: [
            SimpleNamespace(harness_id=h, path=f"/bin/{h}") for h in harness_ids
        ],
    )


def configs(tmp_path: Path, monkeypatch, **payloads: str) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    resolved = {**managed_config_paths(), "claude-cli": claude_settings_path()}
    for harness, payload in payloads.items():
        resolved[harness].parent.mkdir(parents=True, exist_ok=True)
        resolved[harness].write_text(payload, encoding="utf-8")


def test_the_session_roster_is_registered_and_machine_local() -> None:
    registered = {hc.slug for hc in HEALTH_CHECKS}
    assert set(checks.SESSION_SLUGS) <= registered
    assert set(checks.SESSION_SLUGS) <= local_runtime_slugs()


def test_another_signed_out_harness_does_not_block_this_session(monkeypatch):
    registered_as(monkeypatch, "claude-code")
    clis(monkeypatch, "claude-code", "codex")
    calls = []

    def probe(argv, **kwargs):
        calls.append(argv[0])
        signed_in = argv[0].endswith("claude-code")
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"loggedIn": signed_in}), ""
        )

    monkeypatch.setattr(doctor_install, "_run", probe)
    result = run(checks.hc_session_harness_cli_auth)
    assert result.result == "PASS"
    assert calls == ["/bin/claude-code"]


def test_a_signed_out_session_harness_names_its_login(monkeypatch):
    registered_as(monkeypatch, "codex")
    clis(monkeypatch, "codex")
    monkeypatch.setattr(
        doctor_install,
        "_run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "not logged in"),
    )
    result = run(checks.hc_session_harness_cli_auth)
    assert result.result == "FAIL"
    assert "HARNESS_AUTH_UNVERIFIED" in result.detail
    assert "`codex login`" in result.detail


def test_a_missing_session_harness_cli_fails_with_its_install_step(monkeypatch):
    registered_as(monkeypatch, "cursor")
    clis(monkeypatch, "claude-code")
    result = run(checks.hc_session_harness_cli_auth)
    assert result.result == "FAIL"
    assert "HARNESS_CLI_MISSING" in result.detail
    assert "cursor-agent" in result.detail


@pytest.mark.parametrize(
    "fn",
    [checks.hc_session_harness_cli_auth, checks.hc_session_harness_unattended_posture],
)
def test_an_unregistered_session_never_guesses_its_harness(monkeypatch, fn):
    registered_as(monkeypatch, None)
    result = run(fn)
    assert result.result == "FAIL"
    assert "SESSION_HARNESS_UNKNOWN" in result.detail


def posture_result():
    result = run(checks.hc_session_harness_unattended_posture)
    return result.result, result.detail.split(":", 1)[
        0
    ] if result.result != "PASS" else None


@pytest.mark.parametrize("surface", ["codex-cli", "codex-desktop"])
@pytest.mark.parametrize(
    "approval,expected,code",
    [
        ("never", "PASS", None),
        ("on-request", "FAIL", "HARNESS_POSTURE_RESTRICTED"),
    ],
)
def test_codex_reads_the_newest_rollout(
    tmp_path, monkeypatch, surface, approval, expected, code
):
    registered_as(monkeypatch, "codex", surface)
    configs(tmp_path, monkeypatch, codex=UNATTENDED_CODEX)
    target = tmp_path / ".codex" / "sessions" / f"rollout-{SESSION}.jsonl"
    target.parent.mkdir(exist_ok=True)
    rows = [
        {"type": "session_meta", "payload": {"id": SESSION}},
        {
            "type": "turn_context",
            "payload": {
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
            },
        },
        {
            "type": "turn_context",
            "payload": {
                "approval_policy": approval,
                "sandbox_policy": {"type": "danger-full-access"},
            },
        },
    ]
    target.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert posture_result() == (expected, code)


@pytest.mark.parametrize("surface", ["codex-cli", "codex-desktop"])
def test_codex_missing_record_cannot_borrow_config(tmp_path, monkeypatch, surface):
    registered_as(monkeypatch, "codex", surface)
    configs(tmp_path, monkeypatch, codex=UNATTENDED_CODEX)
    assert posture_result() == ("FAIL", "HARNESS_POSTURE_UNVERIFIED")


@pytest.mark.parametrize("surface", ["claude-cli", "claude-desktop", "claude-vscode"])
@pytest.mark.parametrize(
    "mode,expected,code",
    [
        ("bypassPermissions", "PASS", None),
        ("default", "FAIL", "HARNESS_POSTURE_RESTRICTED"),
        ("auto", "FAIL", "HARNESS_POSTURE_RESTRICTED"),
        (None, "FAIL", "HARNESS_POSTURE_RESTRICTED"),
    ],
)
def test_claude_uses_recorded_mode_despite_desktop_preference(
    tmp_path, monkeypatch, surface, mode, expected, code
):
    registered_as(monkeypatch, "claude-code", surface)
    configs(
        tmp_path,
        monkeypatch,
        **{
            "claude-code": '{"preferences":{"bypassPermissionsModeEnabled":true}}',
        },
    )
    capture_permission_mode(
        {"session_id": SESSION, "permission_mode": mode}, "claude-code"
    )
    assert posture_result() == (expected, code)


@pytest.mark.parametrize("surface", ["claude-cli", "claude-desktop", "claude-vscode"])
def test_claude_missing_record_fails(tmp_path, monkeypatch, surface):
    registered_as(monkeypatch, "claude-code", surface)
    configs(tmp_path, monkeypatch)
    assert posture_result() == ("FAIL", "HARNESS_POSTURE_UNVERIFIED")


@pytest.mark.parametrize(
    "harness,surface", [("codex", "codex-vscode"), ("cursor", "cursor-desktop")]
)
def test_confirm_only_surfaces_warn(tmp_path, monkeypatch, harness, surface):
    registered_as(monkeypatch, harness, surface)
    configs(tmp_path, monkeypatch)
    assert posture_result() == ("WARN", "HARNESS_POSTURE_CONFIRM_REQUIRED")


@pytest.mark.parametrize("surface", [None, "unknown"])
def test_unknown_surface_fails(tmp_path, monkeypatch, surface):
    registered_as(monkeypatch, "claude-code")
    monkeypatch.setattr(checks, "session_harness", lambda: ("claude-code", surface))
    configs(tmp_path, monkeypatch)
    assert posture_result() == ("FAIL", "HARNESS_POSTURE_UNVERIFIED")


@pytest.mark.parametrize(
    "config,expected,code",
    [
        (None, "FAIL", "HARNESS_POSTURE_UNVERIFIED"),
        ("{}", "FAIL", "HARNESS_POSTURE_RESTRICTED"),
        (
            json.dumps(
                {
                    "approvalMode": CURSOR_APPROVAL_MODE,
                    "sandbox": {"mode": CURSOR_SANDBOX_MODE},
                }
            ),
            "PASS",
            None,
        ),
    ],
)
def test_cursor_cli_keeps_config_reader(tmp_path, monkeypatch, config, expected, code):
    registered_as(monkeypatch, "cursor")
    configs(tmp_path, monkeypatch, **({"cursor": config} if config else {}))
    assert posture_result() == (expected, code)


def test_unproven_registration_names_only_a_new_session(monkeypatch):
    # Setup mints Codex hook trust, so no harness shows a trust prompt to approve.
    monkeypatch.setattr(
        doctor_install, "build_actor", lambda: SimpleNamespace(session_id="")
    )
    result = run(
        doctor_install.hc_session_hook_registration, only="session-hook-registration"
    )
    assert result.result == "FAIL"
    assert "Start a new harness session" in result.detail
    assert "approve" not in result.detail
    assert "trust" not in result.detail


@pytest.mark.parametrize("quick", [False, True])
@pytest.mark.parametrize(
    "fn",
    [
        doctor_install.hc_session_hook_registration,
        checks.hc_session_harness_cli_auth,
        checks.hc_session_harness_unattended_posture,
    ],
)
def test_ordinary_health_without_a_session_is_not_applicable(monkeypatch, fn, quick):
    for module in (doctor_install, checks):
        monkeypatch.setattr(
            module, "build_actor", lambda: SimpleNamespace(session_id=None)
        )
        monkeypatch.setattr(
            module, "relay", lambda *a: pytest.fail("no session to inspect")
        )
    result = run(fn, quick=quick)
    assert result.result == "N/A"
    assert "session_required" in result.detail
    assert "yoke doctor run --session" in result.detail


@pytest.mark.parametrize(
    "fn,reason",
    [
        (doctor_install.hc_session_hook_registration, "SESSION_HOOK_UNOBSERVED"),
        (checks.hc_session_harness_cli_auth, "SESSION_HARNESS_UNKNOWN"),
        (checks.hc_session_harness_unattended_posture, "SESSION_HARNESS_UNKNOWN"),
    ],
)
def test_explicit_session_readiness_without_a_session_still_fails(
    monkeypatch, fn, reason
):
    for module in (doctor_install, checks):
        monkeypatch.setattr(
            module, "build_actor", lambda: SimpleNamespace(session_id=None)
        )
    result = run(fn, only=",".join(checks.SESSION_SLUGS))
    assert result.result == "FAIL"
    assert reason in result.detail
