"""Reflection ingress retains native clocks before any persistence owner."""

from datetime import datetime
import pytest
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.reflection_capture_shape_parsers import (
    ReflectionEntry,
    _make_entry,
)
from yoke_core.domain import reflection_capture_shape_parsers as shapes
from yoke_core.domain import reflection_capture_freeform as freeform

NOW = parse_instant("2060-10-08T05:45:00.123456+05:45")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize(
    "value", [NOW, "2060-10-08T00:00:00.123456Z", "2060-10-08T05:45:00.123456+05:45"]
)
def test_reflection_record_ingress_is_native_and_preserves_opaque_fields(value):
    entry = ReflectionEntry(value, "codex", OPAQUE, "observation", OPAQUE)
    assert isinstance(entry.timestamp, datetime) and entry.timestamp == NOW
    assert entry.timestamp.microsecond == 123456
    assert entry.context == entry.body == OPAQUE
    assert (
        _make_entry("observation", OPAQUE, "codex", {"timestamp": value}).timestamp
        == NOW
    )


@pytest.mark.parametrize(
    "value", [None, "", "2060-10-08", "2060-10-08T00:00:00", 17, datetime(2060, 10, 8)]
)
def test_supplied_reflection_clock_refuses_at_record_ingress(value):
    with pytest.raises(InvalidInstant):
        ReflectionEntry(value, "codex", OPAQUE, "observation", OPAQUE)
    with pytest.raises(InvalidInstant):
        _make_entry("observation", OPAQUE, "codex", {"timestamp": value})


def test_provided_clock_does_not_evaluate_unused_default(monkeypatch):
    def unused():
        pytest.fail("explicit reflection instant generated another clock")

    monkeypatch.setattr(shapes, "utc_now", unused)
    assert (
        _make_entry("observation", OPAQUE, "codex", {"timestamp": NOW}).timestamp == NOW
    )


def test_canonical_and_freeform_clock_generators_retain_microseconds(monkeypatch):
    for owner in [shapes, freeform]:
        monkeypatch.setattr(owner, "utc_now", lambda: NOW)
        assert owner._now_instant() == NOW
    assert _make_entry("observation", OPAQUE, "codex").timestamp == NOW
    entry = freeform.try_shape_generic_freeform(OPAQUE, "codex")[0]
    assert isinstance(entry.timestamp, datetime) and entry.timestamp == NOW
    assert entry.body == OPAQUE
    for owner in [shapes, freeform]:
        monkeypatch.setattr(owner, "utc_now", lambda: datetime(2060, 10, 8))
        with pytest.raises(InvalidInstant):
            owner._now_instant()
