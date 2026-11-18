"""Harness sign-in WARNs name their real cause.

A CLI that answers "signed out" earns the re-login step. A probe that timed
out, failed or printed nothing readable is not evidence of sign-out, so its
WARN names the command and how it failed instead of prescribing re-login.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_core.engines import doctor_install

CLAUDE = harness_cli_manifest("claude-code")
CODEX = harness_cli_manifest("codex")
ACCOUNT = {"loggedIn": True, "email": "person@example.com"}


def probe(monkeypatch, returncode: int, stdout: str = "", stderr: str = "") -> None:
    monkeypatch.setattr(
        doctor_install,
        "_run",
        lambda argv, **k: subprocess.CompletedProcess(argv, returncode, stdout, stderr),
    )


def test_signed_in_passes_without_echoing_the_account(monkeypatch):
    probe(monkeypatch, 0, json.dumps(ACCOUNT))
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is True
    assert "person@example.com" not in detail


def test_signed_out_names_the_login(monkeypatch):
    probe(monkeypatch, 0, json.dumps({**ACCOUNT, "loggedIn": False}))
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail.startswith("HARNESS_SIGNED_OUT")
    assert "`/bin/claude auth login`" in detail
    assert "person@example.com" not in detail


def test_a_timed_out_probe_names_the_timeout_not_a_login(monkeypatch):
    probe(monkeypatch, 124, "", "timeout after 5s")
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail.startswith(
        "HARNESS_AUTH_PROBE_FAILED: `claude auth status --json` timed out after "
        f"{doctor_install.HARNESS_AUTH_PROBE_TIMEOUT_S}s"
    )
    assert "auth login" not in detail


def test_a_failed_probe_names_its_exit_code_not_a_login(monkeypatch):
    probe(monkeypatch, 1, "", "EACCES: permission denied, open '/x'\nat stack")
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail == (
        "HARNESS_AUTH_PROBE_FAILED: `claude auth status --json` exited 1 without "
        "a JSON status document."
    )
    assert "auth login" not in detail


def test_a_signed_out_cli_that_exits_non_zero_still_names_the_login(monkeypatch):
    # Claude Code 2.1.327 signed out: exit 1, empty stderr, loggedIn false.
    probe(monkeypatch, 1, json.dumps({"loggedIn": False, "authMethod": "none"}))
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail.startswith("HARNESS_SIGNED_OUT")
    assert "`/bin/claude auth login`" in detail


def test_a_signed_in_document_with_a_failing_exit_is_a_probe_failure(monkeypatch):
    probe(monkeypatch, 2, json.dumps(ACCOUNT), "config lock busy")
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail == (
        "HARNESS_AUTH_PROBE_FAILED: `claude auth status --json` exited 2."
    )
    assert "person@example.com" not in detail and "lock" not in detail


def test_the_probe_budget_covers_a_slow_in_session_cli_within_the_check_budget():
    from yoke_contracts.doctor_budget import CHECK_BUDGET_S
    from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS

    assert doctor_install.HARNESS_AUTH_PROBE_TIMEOUT_S > 5.4
    assert doctor_install.HARNESS_AUTH_PROBE_TIMEOUT_S * len(HARNESS_CLI_MANIFESTS) < CHECK_BUDGET_S


@pytest.mark.parametrize("stdout", ["", "Logged in as person@example.com", "[]"])
def test_unreadable_output_is_a_probe_failure_and_never_echoed(monkeypatch, stdout):
    probe(monkeypatch, 0, stdout)
    signed_in, detail = doctor_install.harness_auth(CLAUDE, "/bin/claude")
    assert signed_in is False
    assert detail.startswith("HARNESS_AUTH_PROBE_FAILED")
    assert "person@example.com" not in detail
    assert "auth login" not in detail


def test_a_status_without_a_document_answers_by_exit_code(monkeypatch):
    assert not CODEX.auth_signed_in_key
    probe(monkeypatch, 0, "Logged in using ChatGPT")
    assert doctor_install.harness_auth(CODEX, "/bin/codex") == (
        True,
        "codex is signed in.",
    )
    probe(monkeypatch, 1, "", "Not logged in")
    signed_in, detail = doctor_install.harness_auth(CODEX, "/bin/codex")
    assert signed_in is False
    assert detail.startswith("HARNESS_SIGNED_OUT")
    assert "`/bin/codex login`" in detail and "exited 1" in detail
    probe(monkeypatch, 124, "", "timeout after 5s")
    assert "timed out" in doctor_install.harness_auth(CODEX, "/bin/codex")[1]
