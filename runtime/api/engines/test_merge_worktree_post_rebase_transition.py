"""Fail-closed registered-command resolution for integrated merge trees."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.engines import merge_worktree_tests as mod


ITEM_ID = 4242


def _resp(success: bool, *, result=None, code: str = "", message: str = ""):
    error = None if success else SimpleNamespace(code=code, message=message)
    return SimpleNamespace(success=success, result=result, error=error)


def _patch_dispatcher(monkeypatch, responses):
    """Patch call_dispatcher; *responses* is a list or a single response."""
    queue = list(responses if isinstance(responses, list) else [responses])
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        if not queue:
            raise AssertionError(f"unexpected dispatcher call: {kwargs}")
        return queue.pop(0)

    monkeypatch.setattr(mod, "call_dispatcher", fake)
    return calls


def _detail_resp(status: str = "implementing"):
    return _resp(True, result={"item": {"status": status}})


@pytest.fixture
def ctx():
    return SimpleNamespace(item_id=ITEM_ID, project="example")


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "post_rebase_requirement_failed",
            "attached plan materialization failed",
        ),
        ("actor_session_missing", "no ambient session"),
        (
            "post_rebase_verification_missing",
            "project has no executable registered command",
        ),
    ],
)
def test_resolution_errors_block_registered_project(
    ctx,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    message: str,
) -> None:
    _patch_dispatcher(
        monkeypatch,
        [_detail_resp(), _resp(False, code=code, message=message)],
    )

    with pytest.raises(RuntimeError, match=code):
        mod._registered_verification_command(ctx)


def test_dispatcher_exception_blocks_registered_project(
    ctx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(**_kwargs):
        raise OSError("relay unavailable")

    monkeypatch.setattr(mod, "call_dispatcher", unavailable)
    with pytest.raises(RuntimeError, match="dispatcher failed"):
        mod._registered_verification_command(ctx)


@pytest.mark.parametrize("scope", ["full", "quick"])
def test_success_returns_registered_command(
    ctx,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    calls = _patch_dispatcher(
        monkeypatch,
        [
            _detail_resp(),
            _resp(
                True,
                result={
                    "project": "example",
                    "scope": scope,
                    "command": "python3 verify_tree.py",
                },
            ),
        ],
    )

    assert mod._registered_verification_command(ctx) == (
        scope,
        "python3 verify_tree.py",
        [],
    )
    assert [call["function_id"] for call in calls] == [
        "items.detail.get",
        "merge.tests.post_rebase_requirement",
    ]
    assert calls[1]["target"].item_id == ITEM_ID
    assert calls[1]["payload"] == {"transition_id": "release"}


def test_unknown_release_stage_falls_back_to_reviewing_implementation(
    ctx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_dispatcher(
        monkeypatch,
        [
            _detail_resp("implementing"),
            _resp(
                False,
                code="post_rebase_requirement_failed",
                message="workflow transition 'release' is not in dash@3",
            ),
            _resp(
                True,
                result={
                    "project": "example",
                    "scope": "quick",
                    "command": "python3 verify_tree.py",
                },
            ),
        ],
    )

    assert mod._registered_verification_command(ctx) == (
        "quick",
        "python3 verify_tree.py",
        [],
    )
    assert [c["payload"].get("transition_id") for c in calls[1:]] == [
        "release",
        "reviewing-implementation",
    ]


def test_success_without_executable_command_blocks(
    ctx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dispatcher(
        monkeypatch,
        [_detail_resp(), _resp(True, result={"scope": "full", "command": ""})],
    )

    with pytest.raises(RuntimeError, match="no executable"):
        mod._registered_verification_command(ctx)


def test_ad_hoc_merge_without_item_keeps_generic_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_dispatcher(monkeypatch, _resp(True))
    ctx = SimpleNamespace(item_id=None, project=None)

    assert mod._registered_verification_command(ctx) is None
    assert calls == []


def test_registered_project_without_item_identity_blocks() -> None:
    ctx = SimpleNamespace(item_id=None, project="example")

    with pytest.raises(RuntimeError, match="no resolvable item identity"):
        mod._registered_verification_command(ctx)
