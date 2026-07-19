"""Machine-local Pack operation handler coverage."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import pack_handlers


def test_update_handler_delegates_one_previewable_pack_operation(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(repo_root, **kwargs):
        observed.update({"repo_root": repo_root, **kwargs})
        return {
            "operation": "update",
            "project_id": 7,
            "project_slug": "sample",
            "repo_root": "/tmp/sample",
            "requested_pack": "registry-oidc",
            "plans": [],
            "conflict_count": 0,
            "applied": False,
            "receipt": "/tmp/sample/.yoke/packs.json",
            "refused": False,
        }

    monkeypatch.setattr("yoke_cli.packs.run_pack_operation", fake_run)
    request = FunctionCallRequest(
        function="packs.update.run",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={
            "project": "sample",
            "pack": "registry-oidc",
            "repo_root": "/tmp/sample",
            "accepted_current_paths": [".github/workflows/deploy.yml"],
        },
    )

    outcome = pack_handlers.handle_packs_update(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["operation"] == "update"
    assert observed == {
        "repo_root": "/tmp/sample",
        "project": "sample",
        "pack": "registry-oidc",
        "operation": "update",
        "apply": False,
        "version": None,
        "session_id": "session-1",
        "accepted_current_paths": [".github/workflows/deploy.yml"],
    }


def test_relink_handler_delegates_one_previewable_file_move(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_relink(repo_root, **kwargs):
        observed.update({"repo_root": repo_root, **kwargs})
        return {
            "operation": "relink",
            "project_id": 7,
            "project_slug": "sample",
            "repo_root": "/tmp/sample",
            "pack": "registry-oidc",
            "pack_path": "infra/oidc.py",
            "from_path": "infra/oidc.py",
            "to_path": "infra/components/oidc.py",
            "destination_matches_baseline": False,
            "destination_is_customized": True,
            "applied": False,
            "receipt": "/tmp/sample/.yoke/packs.json",
        }

    monkeypatch.setattr("yoke_cli.packs.run_pack_relink", fake_relink)
    request = FunctionCallRequest(
        function="packs.relink.run",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={
            "project": "sample",
            "pack": "registry-oidc",
            "repo_root": "/tmp/sample",
            "from_path": "infra/oidc.py",
            "to_path": "infra/components/oidc.py",
        },
    )

    outcome = pack_handlers.handle_packs_relink(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["operation"] == "relink"
    assert observed == {
        "repo_root": "/tmp/sample",
        "project": "sample",
        "pack": "registry-oidc",
        "from_path": "infra/oidc.py",
        "to_path": "infra/components/oidc.py",
        "apply": False,
        "session_id": "session-1",
    }
