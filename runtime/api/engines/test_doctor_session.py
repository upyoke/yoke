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
from yoke_core.engines import doctor_hc_harness_unattended_posture as posture
from yoke_core.engines import doctor_install
from yoke_core.engines import doctor_session as checks
from yoke_core.engines.doctor_applicability_declarations import local_runtime_slugs
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

UNATTENDED_CODEX = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
UNATTENDED_CLAUDE_CLI = '{"permissions":{"defaultMode":"bypassPermissions"}}'
UNATTENDED_CLAUDE_DESKTOP = '{"preferences":{"bypassPermissionsModeEnabled":true}}'


def run(fn):
    rec = RecordCollector()
    fn(None, DoctorArgs(project="42"), rec)
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
    resolved = {}
    for harness, name in (
        ("claude-code", "claude/claude_desktop_config.json"),
        ("claude-cli", "claude/settings.json"),
        ("codex", "codex/config.toml"),
        ("cursor", "cursor/cli-config.json"),
    ):
        target = tmp_path / name
        if harness in payloads:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payloads[harness], encoding="utf-8")
        if harness == "claude-cli":
            monkeypatch.setattr(
                posture, "claude_settings_path", lambda target=target: target
            )
        else:
            resolved[harness] = target
    monkeypatch.setattr(posture, "managed_config_paths", lambda: resolved)


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


def test_unproven_registration_names_new_session_and_hook_approval(monkeypatch):
    monkeypatch.setattr(
        doctor_install, "build_actor", lambda: SimpleNamespace(session_id="")
    )
    result = run(doctor_install.hc_session_hook_registration)
    assert result.result == "FAIL"
    assert "Start a new harness session" in result.detail
    assert "Codex's hook-trust prompt" in result.detail
