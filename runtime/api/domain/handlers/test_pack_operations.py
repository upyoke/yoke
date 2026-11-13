"""Machine-local Pack operation handler coverage."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import pack_handlers, pack_remove_handlers


def test_update_handler_delegates_one_previewable_pack_operation(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(repo_root, **kwargs):
        observed.update({"repo_root": repo_root, **kwargs})
        return {
            "operation": "update",
            "project_id": 7,
            "project_slug": "sample",
            "repo_root": "/tmp/sample",
            "requested_pack": "smoke-testing",
            "plans": [],
            "prerequisites": [],
            "unsatisfied_prerequisite_count": 0,
            "conflict_count": 0,
            "allow_missing_tools": False,
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
            "pack": "smoke-testing",
            "repo_root": "/tmp/sample",
            "accepted_current_paths": [".github/workflows/smoke.yml"],
        },
    )

    outcome = pack_handlers.handle_packs_update(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["operation"] == "update"
    assert observed == {
        "repo_root": "/tmp/sample",
        "project": "sample",
        "pack": "smoke-testing",
        "operation": "update",
        "apply": False,
        "allow_missing_tools": False,
        "version": None,
        "session_id": "session-1",
        "accepted_current_paths": [".github/workflows/smoke.yml"],
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
            "pack": "smoke-testing",
            "pack_path": ".github/workflows/smoke.yml",
            "from_path": ".github/workflows/smoke.yml",
            "to_path": ".github/workflows/smoke-test.yml",
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
            "pack": "smoke-testing",
            "repo_root": "/tmp/sample",
            "from_path": ".github/workflows/smoke.yml",
            "to_path": ".github/workflows/smoke-test.yml",
        },
    )

    outcome = pack_handlers.handle_packs_relink(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["operation"] == "relink"
    assert observed == {
        "repo_root": "/tmp/sample",
        "project": "sample",
        "pack": "smoke-testing",
        "from_path": ".github/workflows/smoke.yml",
        "to_path": ".github/workflows/smoke-test.yml",
        "apply": False,
        "session_id": "session-1",
    }


def test_remove_handler_delegates_one_previewable_removal(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_remove(repo_root, **kwargs):
        observed.update({"repo_root": repo_root, **kwargs})
        return {"operation": "remove", "applied": False}

    monkeypatch.setattr("yoke_cli.packs.run_pack_remove", fake_remove)
    request = FunctionCallRequest(
        function="packs.remove.run",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={"project": "sample", "pack": "old-pack", "repo_root": "/tmp/s"},
    )

    outcome = pack_remove_handlers.handle_packs_remove(request)

    assert outcome.primary_success is True
    assert observed == {
        "repo_root": "/tmp/s",
        "project": "sample",
        "pack": "old-pack",
        "apply": False,
        "session_id": "session-1",
    }


def test_remove_handler_names_a_refusal(monkeypatch) -> None:
    from yoke_cli.packs import PackClientError

    def refuse(repo_root, **kwargs):
        raise PackClientError("pack-required-by-installed: Pack 'base'")

    monkeypatch.setattr("yoke_cli.packs.run_pack_remove", refuse)
    request = FunctionCallRequest(
        function="packs.remove.run",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={"project": "sample", "pack": "base"},
    )

    outcome = pack_remove_handlers.handle_packs_remove(request)

    assert outcome.primary_success is False
    assert outcome.error.code == "pack_remove_failed"
    assert "pack-required-by-installed" in outcome.error.message
