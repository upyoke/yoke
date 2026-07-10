from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import projects_capability_secret


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.capability_secret.set",
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_projects_capability_secret_set_rejects_github_case_variants(
    monkeypatch,
) -> None:
    captured = {}

    def _set_secret(project, cap_type, key, *, value, source):
        captured.update({
            "project": project,
            "cap_type": cap_type,
            "key": key,
            "value": value,
            "source": source,
        })

    monkeypatch.setattr(
        "yoke_core.domain.projects_capabilities.cmd_capability_set_secret",
        _set_secret,
    )

    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "demo",
            "cap_type": "GitHub",
            "key": "token",
            "value": "ghs_secret",
        })
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "github_binding_owned"
    assert "stranded" in outcome.error.message
    assert captured == {}


def test_projects_capability_secret_set_forces_literal_source(monkeypatch) -> None:
    captured = {}

    def _set_secret(project, cap_type, key, *, value, source):
        captured.update({"cap_type": cap_type, "value": value, "source": source})

    monkeypatch.setattr(
        "yoke_core.domain.projects_capabilities.cmd_capability_set_secret",
        _set_secret,
    )
    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "demo",
            "cap_type": "deploy",
            "key": "token",
            "value": "secret",
        })
    )

    assert outcome.primary_success is True
    assert captured == {
        "cap_type": "deploy",
        "value": "secret",
        "source": "literal",
    }


def test_projects_capability_secret_set_rejects_external_source() -> None:
    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "demo",
            "cap_type": "deploy",
            "key": "token",
            "value": "/tmp/token",
            "source": "file",
        })
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert "literal" in outcome.error.message


def test_projects_capability_secret_set_rejects_machine_local_aws() -> None:
    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "demo",
            "cap_type": "aws-admin",
            "key": "secret_access_key",
            "value": "secret",
        })
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "machine_local_secret"
    assert "~/.yoke/secrets/capability-secrets" in outcome.error.message


def test_projects_capability_secret_set_rejects_machine_local_ssh_private_key() -> None:
    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "demo",
            "cap_type": "ssh",
            "key": "private_key",
            "value": "secret",
        })
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "machine_local_secret"
    assert "ssh.private_key" in outcome.error.message


def test_projects_capability_secret_set_records_machine_file_metadata(
    monkeypatch,
) -> None:
    captured = {}

    def _mark_file(project, cap_type, key, path):
        captured.update({
            "project": project,
            "cap_type": cap_type,
            "key": key,
            "path": path,
        })

    monkeypatch.setattr(
        "yoke_core.domain.projects_capabilities."
        "cmd_capability_mark_machine_secret_file",
        _mark_file,
    )

    outcome = projects_capability_secret.handle_projects_capability_secret_set(
        _request({
            "project": "buzz",
            "cap_type": "ssh",
            "key": "private_key",
            "source": "machine_file",
            "path": "/Users/example/.yoke/secrets/key",
        })
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "project": "buzz",
        "cap_type": "ssh",
        "key": "private_key",
        "source": "machine_file",
        "stored": True,
        "path": "/Users/example/.yoke/secrets/key",
    }
    assert captured == {
        "project": "buzz",
        "cap_type": "ssh",
        "key": "private_key",
        "path": "/Users/example/.yoke/secrets/key",
    }
