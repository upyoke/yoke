"""Independent local boundary for temporary private-route authority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import RelayInstance
from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
    PrivateRouteQualificationScope,
)
from yoke_core.tools.session_relay_plist import (
    relay_launchd_paths,
    relay_plist_document,
)
from yoke_harness import session_relay_private_qualification as qualification
from yoke_harness.session_relay_claude import (
    ClaudeProcessResult,
    run_claude_cli_adapter,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


RELEASE_SHA = "a" * 40
TARGET_SESSION_ID = "22222222-2222-4222-8222-222222222222"


def _scope(**changes: str) -> PrivateRouteQualificationScope:
    values = {
        "release_sha": RELEASE_SHA,
        "acceptance_run_id": "stage-private-proof",
        "surface": "claude-cli",
        "version": "2.1.241",
        "operation": "message_stopped",
        "route": "direct",
    }
    values.update(changes)
    return PrivateRouteQualificationScope(**values)


def _grant(
    *,
    scope: PrivateRouteQualificationScope | None = None,
    project_id: int = 1,
    digest: str | None = None,
    expired: bool = False,
) -> PrivateRouteQualificationGrant:
    private_scope = scope or _scope()
    current = datetime.now(timezone.utc)
    return PrivateRouteQualificationGrant(
        lease_id=81,
        project_id=project_id,
        sender_session_id="operator-session",
        operator_actor_id="169",
        opened_at=(current - timedelta(minutes=1)).isoformat(),
        expires_at=(
            current - timedelta(seconds=1)
            if expired
            else current + timedelta(minutes=20)
        ).isoformat(),
        grant_digest=digest or private_scope.digest,
        scope=private_scope,
    )


def _context(tmp_path, *, grant=None, version: str = "2.1.241"):
    return RelayExecutionContext(
        job_kind="wake",
        job_id="attempt-1",
        lease_id="relay-lease-1",
        surface="claude-cli",
        project_id=1,
        checkout=tmp_path,
        native_instruction="Yoke message message-1: check your Yoke messages.",
        surface_version=version,
        message_id="message-1",
        target_session_id=TARGET_SESSION_ID,
        target_liveness="ended",
        wake_mode="waiting",
        wake_route="direct",
        private_route_qualification=grant,
    )


def _stage_runtime(
    monkeypatch,
    *,
    prod: bool = False,
    active_environment: str = "stage",
):
    monkeypatch.setattr(
        qualification.machine_config, "active_env", lambda: active_environment
    )
    monkeypatch.setattr(
        qualification.machine_config,
        "active_connection",
        lambda: {"transport": "https", "prod": prod},
    )


def _git_result(*, dirty: bool = False, head: str = RELEASE_SHA):
    def run(argv, **_kwargs):
        stdout = f"{head}\n" if "rev-parse" in argv else (" M file\n" if dirty else "")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return run


def test_exact_clean_stage_scope_is_allowed(monkeypatch, tmp_path) -> None:
    _stage_runtime(monkeypatch)
    monkeypatch.setattr(qualification.subprocess, "run", _git_result())

    assert qualification.private_route_qualification_allows(
        _context(tmp_path, grant=_grant()), operation="message_stopped"
    )


def test_registered_target_checkout_does_not_stand_in_for_relay_source(
    monkeypatch, tmp_path
) -> None:
    _stage_runtime(monkeypatch)
    target_checkout = tmp_path / "registered-target"
    target_checkout.mkdir()
    (target_checkout / "dirty.txt").write_text("not relay source", encoding="utf-8")
    source_checkout = Path(qualification.__file__).resolve().parent
    observed: list[Path] = []

    def run(argv, **_kwargs):
        observed.append(Path(argv[2]))
        stdout = f"{RELEASE_SHA}\n" if "rev-parse" in argv else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(qualification.subprocess, "run", run)

    assert qualification.private_route_qualification_allows(
        _context(target_checkout, grant=_grant()), operation="message_stopped"
    )
    assert observed == [source_checkout, source_checkout]


@pytest.mark.parametrize(
    ("active_environment", "prod"),
    [("prod", False), ("stage", True)],
)
def test_prod_active_environment_or_connection_is_refused(
    monkeypatch,
    tmp_path,
    active_environment: str,
    prod: bool,
) -> None:
    _stage_runtime(
        monkeypatch,
        prod=prod,
        active_environment=active_environment,
    )
    monkeypatch.setattr(qualification.subprocess, "run", _git_result())

    assert not qualification.private_route_qualification_allows(
        _context(tmp_path, grant=_grant()), operation="message_stopped"
    )


def test_launchd_projection_authorizes_connection_derived_stage(
    monkeypatch, tmp_path
) -> None:
    yoke_home = tmp_path / ".yoke"
    instance = RelayInstance(
        environment="stage",
        config_path=yoke_home / "config.json",
        yoke_home=yoke_home,
        prod=False,
        label="com.upyoke.relay.stage-test",
        state_dir=yoke_home / "relay-instances" / "stage-test",
    )
    document = relay_plist_document(
        executable=tmp_path / "bin" / "yoke",
        paths=relay_launchd_paths(home=tmp_path, instance=instance),
        environ={"PATH": "/usr/bin:/bin"},
    )
    assert document["ProgramArguments"][1:3] == ["--env", "stage"]
    environment = document["EnvironmentVariables"]
    assert set(environment) == {
        "PATH",
        machine_config.CONFIG_FILE_ENV,
        machine_config.HOME_ENV,
    }
    assert "YOKE_ENVIRONMENT" not in environment
    monkeypatch.delenv("YOKE_ENVIRONMENT", raising=False)
    _stage_runtime(monkeypatch)
    monkeypatch.setattr(qualification.subprocess, "run", _git_result())

    assert qualification.private_route_qualification_allows(
        _context(tmp_path, grant=_grant()), operation="message_stopped"
    )


@pytest.mark.parametrize(
    "grant",
    [
        _grant(expired=True),
        _grant(digest="b" * 64),
        _grant(project_id=2),
        _grant(scope=_scope(surface="claude-desktop", version="1.34493.1")),
        _grant(scope=_scope(version="2.1.242")),
        _grant(scope=_scope(operation="message_idle")),
        _grant(scope=_scope(route="broker")),
    ],
)
def test_expired_or_mismatched_envelope_is_refused(
    monkeypatch, tmp_path, grant: PrivateRouteQualificationGrant
) -> None:
    _stage_runtime(monkeypatch)
    monkeypatch.setattr(qualification.subprocess, "run", _git_result())

    assert not qualification.private_route_qualification_allows(
        _context(tmp_path, grant=grant), operation="message_stopped"
    )


@pytest.mark.parametrize(
    ("dirty", "head"),
    [(True, RELEASE_SHA), (False, "b" * 40), (False, "a" * 12)],
)
def test_relay_source_must_be_clean_at_the_exact_full_release(
    monkeypatch, tmp_path, dirty: bool, head: str
) -> None:
    _stage_runtime(monkeypatch)
    monkeypatch.setattr(
        qualification.subprocess,
        "run",
        _git_result(dirty=dirty, head=head),
    )

    assert not qualification.private_route_qualification_allows(
        _context(tmp_path, grant=_grant()), operation="message_stopped"
    )


def test_claude_adapter_keeps_canonical_first_and_fallback_exact(
    monkeypatch, tmp_path
) -> None:
    _stage_runtime(monkeypatch)
    monkeypatch.setattr(qualification, "_clean_source_sha", lambda: RELEASE_SHA)

    def runner(invocation):
        return ClaudeProcessResult(
            0,
            4,
            stdout=json.dumps({"session_id": invocation.session_id}),
        )

    def finder(_name):
        return "/opt/claude"

    canonical = run_claude_cli_adapter(
        _context(tmp_path, version="2.1.238"),
        process_runner=runner,
        executable_finder=finder,
    )
    qualified = run_claude_cli_adapter(
        _context(tmp_path, grant=_grant()),
        process_runner=runner,
        executable_finder=finder,
    )
    refused = run_claude_cli_adapter(
        _context(tmp_path, grant=_grant(digest="b" * 64)),
        process_runner=runner,
        executable_finder=finder,
    )

    assert canonical.result_code == "accepted"
    assert qualified.result_code == "accepted"
    assert refused.result_code == "version_mismatch"
