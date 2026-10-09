"""Generated strategy identity preserves instants and body bytes."""

from datetime import datetime, timezone

import pytest

from yoke_contracts.project_contract import strategy_docs_header as header
from yoke_contracts.project_contract import strategy_docs_io as files
from yoke_contracts.project_contract.strategy_docs_paths import strategy_view_path
from yoke_contracts.timestamps import InvalidInstant

STAMP = datetime(2026, 6, 11, 9, 0, 0, 123456, tzinfo=timezone.utc)
WIRE = "2026-06-11T09:00:00.123456Z"
OFFSET = "2026-06-11T11:00:00.123456+02:00"
BODY = "# Mission\n\nZoë — body bytes\n\n"
BAD = [
    None,
    "",
    "2026-06-11T09:00:00",
    "2026-06-11 09:00:00+00:00",
    "2026-06-11T09:00:00-00:00",
    datetime(2026, 6, 11),
]


@pytest.mark.parametrize("clock", [STAMP, WIRE, OFFSET])
def test_rendered_clock_canonicalizes_without_changing_content(clock):
    text = header.render_file_text("MISSION", clock, BODY, updated_by="Zoë")
    parsed = header.parse_file_text(text)
    assert parsed.updated_at == WIRE
    assert parsed.body == BODY
    assert parsed.updated_by == "Zoë"
    assert parsed.content_sha256 == header.content_sha256(BODY)
    assert text == header.render_file_text("MISSION", STAMP, BODY, updated_by="Zoë")


@pytest.mark.parametrize("clock", [OFFSET, "2026-06-11T09:00:00Z"])
def test_qualified_existing_header_uses_canonical_compare_identity(clock):
    text = header.render_file_text("MISSION", STAMP, BODY).replace(WIRE, clock)
    parsed = header.parse_file_text(text)
    expected = WIRE if clock == OFFSET else "2026-06-11T09:00:00.000000Z"
    assert parsed.updated_at == expected
    assert parsed.body == BODY
    assert parsed.content_sha256 == header.content_sha256(BODY)


@pytest.mark.parametrize("clock", BAD)
def test_render_refuses_unqualified_required_clock(clock):
    with pytest.raises(InvalidInstant):
        header.render_file_text("MISSION", clock, BODY)


@pytest.mark.parametrize(
    "clock", ["now", "2026-06-11T09:00:00", "2026-06-11T09:00:00-00:00"]
)
def test_invalid_clock_is_a_mangled_generated_header(clock):
    text = header.render_file_text("MISSION", STAMP, BODY).replace(WIRE, clock)
    with pytest.raises(header.StrategyHeaderError) as exc:
        header.parse_file_text(text)
    assert exc.value.kind == "mangled"


@pytest.mark.parametrize("clock", [STAMP, OFFSET])
def test_archive_relocation_matches_equal_instant_and_preserves_bytes(tmp_path, clock):
    active = strategy_view_path(tmp_path, "MISSION")
    active.parent.mkdir(parents=True)
    text = header.render_file_text("MISSION", STAMP, BODY).replace(WIRE, OFFSET)
    active.write_text(text)
    original = active.read_bytes()
    assert (
        files.relocate_generated_archive(
            tmp_path,
            "MISSION",
            updated_at=clock,
            content_sha256=header.content_sha256(BODY),
        )
        == "archived"
    )
    assert not active.exists()
    assert strategy_view_path(tmp_path, "MISSION", True).read_bytes() == original


@pytest.mark.parametrize("clock", BAD)
def test_archive_refuses_clock_before_read_or_move(tmp_path, clock, monkeypatch):
    def unexpected(*args):
        pytest.fail("filesystem inspection preceded clock validation")

    monkeypatch.setattr(files, "inspect_local_renders", unexpected)
    with pytest.raises(InvalidInstant):
        files.relocate_generated_archive(
            tmp_path,
            "MISSION",
            updated_at=clock,
            content_sha256=header.content_sha256(BODY),
        )
