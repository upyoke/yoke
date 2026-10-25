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
from yoke_core.engines.doctor_applicability_declarations import local_runtime_slugs
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

UNATTENDED_CODEX = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
UNATTENDED_CLAUDE_CLI = '{"permissions":{"defaultMode":"bypassPermissions"}}'
UNATTENDED_CLAUDE_DESKTOP = '{"preferences":{"bypassPermissionsModeEnabled":true}}'


def run(fn, **kwargs):
    rec = RecordCollector()
    fn(None, DoctorArgs(project="42", **kwargs), rec)
    assert len(rec.results) == 1
    return rec.results[0]


def registered_as(
    monkeypatch, executor: str | None, surface: str | None = None
) -> None:
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    identity = {
        "session_id": "session" if executor else "other",
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


def test_posture_reads_only_the_session_harness(tmp_path, monkeypatch):
    registered_as(monkeypatch, "codex")
    configs(tmp_path, monkeypatch, codex=UNATTENDED_CODEX, cursor="{}")
    result = run(checks.hc_session_harness_unattended_posture)
    assert result.result == "PASS"
    assert "codex" in result.detail


def test_a_session_harness_without_config_fails(tmp_path, monkeypatch):
    registered_as(monkeypatch, "cursor")
    configs(tmp_path, monkeypatch)
    result = run(checks.hc_session_harness_unattended_posture)
    assert result.result == "FAIL"
    assert "HARNESS_POSTURE_UNVERIFIED" in result.detail


@pytest.mark.parametrize(
    "surface,cli,desktop,expected",
    [
        ("claude-cli", UNATTENDED_CLAUDE_CLI, None, "PASS"),
        ("claude-cli", UNATTENDED_CLAUDE_CLI, "malformed", "PASS"),
        (
            "claude-cli",
            '{"permissions":{"defaultMode":"default"}}',
            UNATTENDED_CLAUDE_DESKTOP,
            "FAIL",
        ),
        ("claude-cli", None, UNATTENDED_CLAUDE_DESKTOP, "FAIL"),
        ("claude-desktop", None, UNATTENDED_CLAUDE_DESKTOP, "PASS"),
        ("claude-desktop", UNATTENDED_CLAUDE_CLI, "{}", "FAIL"),
    ],
)
def test_claude_readiness_uses_only_the_registered_surface_config(
    tmp_path, monkeypatch, surface, cli, desktop, expected
):
    registered_as(monkeypatch, "claude-code", surface)
    payloads = {}
    if cli is not None:
        payloads["claude-cli"] = cli
    if desktop is not None:
        payloads["claude-code"] = desktop
    configs(tmp_path, monkeypatch, **payloads)
    result = run(checks.hc_session_harness_unattended_posture)
    assert result.result == expected
    if surface == "claude-cli" and expected == "FAIL":
        assert "claude_desktop_config" not in result.detail


@pytest.mark.parametrize("surface", [None, "claude-vscode"])
def test_unverified_claude_surface_cannot_borrow_desktop_posture(
    tmp_path, monkeypatch, surface
):
    registered_as(monkeypatch, "claude-code")
    monkeypatch.setattr(
        checks,
        "relay",
        lambda *a: {
            "session_id": "session",
            "executor": "claude-code",
            "executor_surface": surface,
        },
    )
    configs(tmp_path, monkeypatch, **{"claude-code": UNATTENDED_CLAUDE_DESKTOP})
    result = run(checks.hc_session_harness_unattended_posture)
    assert result.result == "FAIL"
    assert (
        "SURFACE_UNKNOWN" in result.detail
        or "no verified posture reader" in result.detail
    )
    assert "harness-setup --fix" not in result.detail


@pytest.mark.parametrize("harness,surface,expected", [
    ("codex", "codex-cli", "PASS"),
    ("codex", "codex-desktop", "FAIL"),
    ("codex", "codex-vscode", "FAIL"),
    ("cursor", "cursor-cli", "PASS"),
    ("cursor", "cursor-desktop", "FAIL"),
])
def test_session_posture_requires_a_verified_surface_reader(
    tmp_path, monkeypatch, harness, surface, expected
):
    registered_as(monkeypatch, harness, surface)
    configs(
        tmp_path, monkeypatch, codex=UNATTENDED_CODEX,
        cursor=json.dumps({"approvalMode": CURSOR_APPROVAL_MODE,
                           "sandbox": {"mode": CURSOR_SANDBOX_MODE}}),
    )
    result = run(checks.hc_session_harness_unattended_posture)
    assert result.result == expected
    if expected == "FAIL":
        assert "HARNESS_POSTURE_UNVERIFIED" in result.detail
        assert f"{surface} has no verified posture reader" in result.detail
        assert "Report the surface to Yoke support" in result.detail
        assert "harness-setup --fix" not in result.detail


def test_unproven_registration_names_new_session_and_hook_approval(monkeypatch):
    monkeypatch.setattr(
        doctor_install, "build_actor", lambda: SimpleNamespace(session_id="")
    )
    result = run(doctor_install.hc_session_hook_registration, only="session-hook-registration")
    assert result.result == "FAIL"
    assert "Start a new harness session" in result.detail
    assert "Codex's hook-trust prompt" in result.detail


@pytest.mark.parametrize("quick", [False, True])
@pytest.mark.parametrize("fn", [
    doctor_install.hc_session_hook_registration,
    checks.hc_session_harness_cli_auth,
    checks.hc_session_harness_unattended_posture,
])
def test_ordinary_health_without_a_session_is_not_applicable(monkeypatch, fn, quick):
    for module in (doctor_install, checks):
        monkeypatch.setattr(module, "build_actor", lambda: SimpleNamespace(session_id=None))
        monkeypatch.setattr(module, "relay", lambda *a: pytest.fail("no session to inspect"))
    result = run(fn, quick=quick)
    assert result.result == "N/A"
    assert "session_required" in result.detail
    assert "yoke doctor run --session" in result.detail


@pytest.mark.parametrize("fn,reason", [
    (doctor_install.hc_session_hook_registration, "SESSION_HOOK_UNOBSERVED"),
    (checks.hc_session_harness_cli_auth, "SESSION_HARNESS_UNKNOWN"),
    (checks.hc_session_harness_unattended_posture, "SESSION_HARNESS_UNKNOWN"),
])
def test_explicit_session_readiness_without_a_session_still_fails(monkeypatch, fn, reason):
    for module in (doctor_install, checks):
        monkeypatch.setattr(module, "build_actor", lambda: SimpleNamespace(session_id=None))
    result = run(fn, only=",".join(checks.SESSION_SLUGS))
    assert result.result == "FAIL"
    assert reason in result.detail
