"""Progress Log append body budgets apply before persistence or publication."""

from unittest.mock import Mock
import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import (
    item_field_transform,
    item_field_transform_sections as owner,
)
from yoke_core.domain.handlers import items_progress_log


@pytest.fixture
def section_store(monkeypatch):
    store = {}
    read = Mock(side_effect=lambda item_id, section: store.get(section))
    write = Mock(
        side_effect=lambda **kw: store.update({kw["section_name"]: kw["content"]})
    )
    render = Mock(return_value=True)
    emit = Mock()
    sync = Mock(return_value=(True, "", "ok", 0))
    monkeypatch.setattr(owner._sections, "get_section", read)
    monkeypatch.setattr(owner._sections, "upsert_section", write)
    monkeypatch.setattr(owner._sections, "_rerender_body", render)
    monkeypatch.setattr(owner._sections, "_emit_section_event", emit)
    monkeypatch.setattr(owner, "sync_section_body", sync)
    return store, (read, write, render, emit, sync)


def append(content, section="Progress Log"):
    return item_field_transform.section_append(
        item_id=42, section=section, headline="checkpoint", content=content
    )


@pytest.mark.parametrize("content", ["x" * 4096, "é" * 2048])
def test_exact_utf8_body_limit_is_accepted(section_store, content):
    store, _ = section_store
    assert append(content).success
    assert content in store["Progress Log"]


@pytest.mark.parametrize("content", ["x" * 4097, "é" * 2048 + "x", "x" * 4096 + "\n"])
def test_oversized_body_refuses_before_any_side_effect(section_store, content):
    store, effects = section_store
    store["Progress Log"] = "Existing entries stay unchanged.\n"
    result = append(content)
    assert not result.success
    assert result.error == (
        "progress_log_entry_too_large: entry body is 4097 UTF-8 bytes; maximum is 4096. "
        "Progress Log entries are current-state checkpoints: write only what changed "
        "and the next step; move evidence to artifacts or feedback."
    )
    assert store["Progress Log"] == "Existing entries stay unchanged.\n"
    for effect in effects:
        effect.assert_not_called()


def test_budget_is_per_entry_body_and_specific_to_progress_log(section_store):
    store, _ = section_store
    store["Progress Log"] = "old evidence\n" * 1000
    assert append("x" * 4096).success
    assert append("x" * 4097, section="Investigation").success


def test_registered_append_surfaces_named_refusal_and_recovery(section_store):
    _, effects = section_store
    request = FunctionCallRequest(
        function="items.progress_log.append",
        actor=ActorContext(session_id="session", actor_id="agent"),
        target=TargetRef(kind="item", item_id=42),
        payload={"headline": "checkpoint", "content": "x" * 4097},
    )
    result = items_progress_log.handle_append(request)
    assert not result.primary_success
    assert result.error is not None
    assert "progress_log_entry_too_large" in result.error.message
    assert "write only what changed and the next step" in result.error.message
    for effect in effects:
        effect.assert_not_called()
