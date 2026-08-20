"""Merge preparation routes numbered-history proof through live read APIs."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import migration_merge_preflight as migration_gate
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines import merge_worktree_prepare_preflight as preflight
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _response(function_id: str, result=None, *, success=True):
    return FunctionCallResponse(
        success=success,
        function=function_id,
        version="v1",
        result=result or {},
    )


def _clean_git(args, *, cwd=None, capture=False, check=False):
    if args[:1] == ["rev-parse"]:
        return SimpleNamespace(stdout="", returncode=1)
    return SimpleNamespace(stdout="", returncode=0)


def _profile(identifier: str) -> str:
    return json.dumps(
        {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [identifier],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [],
            "count_preserving": True,
        }
    )


def _run(monkeypatch, *, profile: str, item_list_success: bool = True):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        function_id = kwargs["function_id"]
        if function_id == "merge.preflight.dependency_gate":
            return _response(function_id, {"is_blocked": False})
        if function_id == "merge.preflight.blocked_gate":
            return _response(function_id, {"applicable": False})
        if function_id == "items.list.run":
            return _response(
                function_id,
                {
                    "rows": [
                        {
                            "id": "42",
                            "status": "reviewing-implementation",
                            "db_mutation_profile": profile,
                        }
                    ]
                },
                success=item_list_success,
            )
        if function_id == "projects.capability_settings.get":
            return _response(function_id, {"settings_json": "{}"})
        raise AssertionError(function_id)

    monkeypatch.setattr(preflight, "call_dispatcher", dispatch)
    monkeypatch.setattr(mw, "_run_git", _clean_git)
    context = MergeContext(
        args=MergeArgs(branch="YOK-42", target="main", standalone=True),
        worktree_path="/tmp/migration-lane",
        item_id="42",
        project="yoke",
    )
    return preflight.preflight_checks(context), calls


def test_numbered_item_relays_roster_and_capability_then_blocks(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(
        migration_gate,
        "evaluate_migration_merge",
        lambda **_kwargs: migration_gate.MigrationMergeGate(
            True, ("synthetic ordinal conflict",)
        ),
    )

    result, calls = _run(monkeypatch, profile=_profile("0015_new"))

    assert result is not None
    called = [call["function_id"] for call in calls]
    assert "items.list.run" in called
    assert "projects.capability_settings.get" in called
    assert "synthetic ordinal conflict" in capsys.readouterr().err


def test_slug_only_item_skips_capability_read(monkeypatch) -> None:
    result, calls = _run(monkeypatch, profile=_profile("legacy_module"))

    assert result is None
    called = [call["function_id"] for call in calls]
    assert "items.list.run" in called
    assert "projects.capability_settings.get" not in called


def test_item_roster_unavailable_fails_closed(monkeypatch, capsys) -> None:
    result, _ = _run(
        monkeypatch,
        profile=_profile("0015_new"),
        item_list_success=False,
    )

    assert result is not None
    assert "Migration-history item roster unavailable" in capsys.readouterr().err
