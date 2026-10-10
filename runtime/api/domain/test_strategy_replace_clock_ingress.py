"""Strategy replacement validates required CAS clocks before reading rows."""

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import strategy_docs

WIRE = "2026-07-14T00:00:00.123456Z"
CLOCK = parse_instant(WIRE)
BODY = strategy_docs.normalize_fields("## Summary\nNative clocks\n\n## State\ndraft\n")


@pytest.mark.parametrize(
    "clock",
    [
        "now",
        "2026-07-14T00:00:00",
        "2026-07-14T00:00:00-00:00",
        CLOCK.replace(tzinfo=None),
    ],
)
def test_invalid_cas_clock_refuses_before_content_or_database_access(
    monkeypatch, clock
):
    def unexpected(*args, **kwargs):
        pytest.fail("reader/body handling preceded clock validation")

    monkeypatch.setattr(strategy_docs, "get_doc", unexpected)
    monkeypatch.setattr(
        strategy_docs._header, "strip_render_header_if_present", unexpected
    )
    with pytest.raises(InvalidInstant):
        strategy_docs.replace_doc(
            None, 1, "MISSION", "replacement", None, base_updated_at=clock
        )


@pytest.mark.parametrize("clock", [CLOCK, "2026-07-14T05:45:00.123456+05:45"])
def test_equal_native_cas_instant_retains_noop_wire_identity(monkeypatch, clock):
    monkeypatch.setattr(
        strategy_docs, "get_doc", lambda *args: {"content": BODY, "updated_at": WIRE}
    )
    result = strategy_docs.replace_doc(
        None, 1, "MISSION", BODY, None, base_updated_at=clock
    )
    assert result["unchanged"] is True
    assert result["updated_at"] == WIRE
