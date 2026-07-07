"""The CLI attaches the project's label-color override delta to the request."""

from __future__ import annotations

from yoke_cli.transport import dispatcher
from yoke_contracts.api.function_call import ActorContext, TargetRef


def _build(monkeypatch, overrides, options=None):
    monkeypatch.setattr(dispatcher, "_label_overrides_loaded", True)
    monkeypatch.setattr(dispatcher, "_label_overrides_value", overrides)
    return dispatcher.build_request(
        function_id="items.get",
        target=TargetRef(kind="global"),
        actor=ActorContext(session_id="test-session"),
        options=options,
    )


def test_build_request_attaches_label_overrides(monkeypatch) -> None:
    req = _build(monkeypatch, {"label_color_status": "AABBCC"})
    assert req.options.get("label_color_overrides") == {"label_color_status": "AABBCC"}


def test_build_request_no_overrides_attaches_nothing(monkeypatch) -> None:
    req = _build(monkeypatch, {})
    assert "label_color_overrides" not in req.options


def test_build_request_preserves_explicit_overrides(monkeypatch) -> None:
    req = _build(
        monkeypatch,
        {"label_color_status": "AABBCC"},
        options={"label_color_overrides": {"label_color_status": "ZZZZZZ"}},
    )
    # An explicitly-provided value is not clobbered by the auto-injection.
    assert req.options["label_color_overrides"] == {"label_color_status": "ZZZZZZ"}
