"""Tests for the idempotent strategy render header.

Pins the byte-precise round-trip contract: the body hash excludes the
header line (and its newline) exactly, so parse-after-render reproduces
the embedded hash for any content shape.
"""

from __future__ import annotations

import hashlib

import pytest

from yoke_core.domain import strategy_docs_header as hdr


class TestBuild:
    def test_header_is_one_line_with_all_fields(self) -> None:
        line = hdr.build_header_line("MISSION", "2026-06-10T00:00:00Z", "body\n")
        assert "\n" not in line
        assert line.startswith(hdr.HEADER_MARKER)
        assert line.endswith(" -->")
        assert "slug=MISSION" in line
        assert "updated_at=2026-06-10T00:00:00Z" in line
        assert f"content_sha256={hdr.content_sha256('body' + chr(10))}" in line

    def test_notice_names_db_authority_and_ingest(self) -> None:
        line = hdr.build_header_line("PAD", "2026-06-10T00:00:00Z", "x\n")
        assert "DB is authoritative" in line
        assert "yoke strategy ingest PAD" in line

    def test_no_wall_clock_input_same_inputs_same_bytes(self) -> None:
        a = hdr.render_file_text("VISION", "2026-06-10T00:00:00Z", "content\n")
        b = hdr.render_file_text("VISION", "2026-06-10T00:00:00Z", "content\n")
        assert a == b

    def test_updated_by_renders_and_round_trips(self) -> None:
        line = hdr.build_header_line(
            "MISSION", "2026-06-10T00:00:00Z", "body\n", updated_by="ben",
        )
        assert "updated_by=ben" in line
        parsed = hdr.parse_file_text(
            hdr.render_file_text(
                "MISSION", "2026-06-10T00:00:00Z", "body\n", updated_by="ben",
            )
        )
        assert parsed.updated_by == "ben"
        assert parsed.body == "body\n"
        # The label is display-only: it does not enter the content hash.
        assert parsed.content_sha256 == hdr.content_sha256("body\n")

    def test_updated_by_omitted_when_absent_and_parses_to_none(self) -> None:
        text = hdr.render_file_text("MISSION", "2026-06-10T00:00:00Z", "b\n")
        assert "updated_by=" not in text.splitlines()[0]
        assert hdr.parse_file_text(text).updated_by is None

    def test_updated_by_is_byte_idempotent(self) -> None:
        a = hdr.render_file_text(
            "VISION", "2026-06-10T00:00:00Z", "c\n", updated_by="ben",
        )
        b = hdr.render_file_text(
            "VISION", "2026-06-10T00:00:00Z", "c\n", updated_by="ben",
        )
        assert a == b

    def test_content_sha256_pinned_vector(self) -> None:
        # Pin the hash construction byte-precisely: sha256 over the raw
        # UTF-8 body bytes, nothing prepended or appended.
        assert hdr.content_sha256("abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        assert hdr.content_sha256("abc") == hashlib.sha256(b"abc").hexdigest()


class TestRoundTrip:
    @pytest.mark.parametrize(
        "content",
        [
            "plain\n",
            "no trailing newline",
            "",  # empty body still round-trips byte-precisely
            "# H\n\nmulti\nline\n\n\ntrailing blanks\n\n",
            "unicode — em-dash and ünïcode\n",
            "\nbody that starts with a blank line\n",
        ],
    )
    def test_parse_recovers_body_and_hash(self, content: str) -> None:
        rendered = hdr.render_file_text("WISPS", "2026-06-11T09:00:00Z", content)
        parsed = hdr.parse_file_text(rendered)
        assert parsed.slug == "WISPS"
        assert parsed.updated_at == "2026-06-11T09:00:00Z"
        assert parsed.body == content
        assert hdr.content_sha256(parsed.body) == parsed.content_sha256

    def test_body_hash_excludes_header_line(self) -> None:
        content = "the body\n"
        rendered = hdr.render_file_text("PAD", "2026-06-10T00:00:00Z", content)
        parsed = hdr.parse_file_text(rendered)
        # The embedded hash is over the body alone — hashing the full
        # rendered file must NOT reproduce it.
        assert parsed.content_sha256 == hdr.content_sha256(content)
        assert parsed.content_sha256 != hdr.content_sha256(rendered)


class TestStripRenderHeaderIfPresent:
    def test_plain_content_is_unchanged(self) -> None:
        body = "# Mission\n\nplain body\n"
        assert hdr.strip_render_header_if_present(
            body, expected_slug="MISSION",
        ) == body

    def test_rendered_content_returns_body(self) -> None:
        body = "# Mission\n\nedited body\n"
        rendered = hdr.render_file_text(
            "MISSION", "2026-06-10T00:00:00Z", body,
        )

        assert hdr.strip_render_header_if_present(
            rendered, expected_slug="MISSION",
        ) == body

    def test_wrong_slug_header_is_refused(self) -> None:
        rendered = hdr.render_file_text(
            "VISION", "2026-06-10T00:00:00Z", "# Vision\n",
        )

        with pytest.raises(hdr.StrategyHeaderError) as exc:
            hdr.strip_render_header_if_present(
                rendered, expected_slug="MISSION",
            )

        assert exc.value.kind == "slug_mismatch"
        assert "VISION" in str(exc.value)
        assert "MISSION" in str(exc.value)


class TestParseFailures:
    def test_missing_header(self) -> None:
        with pytest.raises(hdr.StrategyHeaderError) as exc:
            hdr.parse_file_text("# Just markdown\n\nno header\n")
        assert exc.value.kind == "missing"

    def test_mangled_header_bad_hash_length(self) -> None:
        broken = (
            "<!-- YOKE:STRATEGY-DOC slug=PAD "
            "updated_at=2026-06-10T00:00:00Z content_sha256=deadbeef "
            "notice -->\nbody\n"
        )
        with pytest.raises(hdr.StrategyHeaderError) as exc:
            hdr.parse_file_text(broken)
        assert exc.value.kind == "mangled"

    def test_mangled_header_truncated_line(self) -> None:
        truncated = hdr.build_header_line(
            "PAD", "2026-06-10T00:00:00Z", "body\n"
        )[:-4]  # drop the closing ' -->'
        with pytest.raises(hdr.StrategyHeaderError) as exc:
            hdr.parse_file_text(truncated + "\nbody\n")
        assert exc.value.kind == "mangled"

    def test_header_with_no_body_separator(self) -> None:
        line = hdr.build_header_line("PAD", "2026-06-10T00:00:00Z", "body\n")
        with pytest.raises(hdr.StrategyHeaderError) as exc:
            hdr.parse_file_text(line)  # no newline after the header at all
        assert exc.value.kind == "mangled"


class TestRenderRefusesEmbeddedHeader:
    """The render boundary makes a double-header view impossible: feeding
    an already-rendered file back in as ``content`` is refused, not
    silently re-wrapped into two stacked headers."""

    def test_render_file_text_refuses_already_headered_content(self) -> None:
        rendered = hdr.render_file_text(
            "MISSION", "2026-06-10T00:00:00Z", "# Mission\n\nbody\n"
        )
        with pytest.raises(hdr.StrategyHeaderError) as exc:
            # A second render of the rendered file would stack headers.
            hdr.render_file_text("MISSION", "2026-06-11T00:00:00Z", rendered)
        assert exc.value.kind == "content_has_header"
        assert "MISSION" in str(exc.value)

    def test_marker_mid_body_does_not_trigger_refusal(self) -> None:
        # The guard is anchored at the start: a body that merely mentions
        # the marker mid-text is not a stacked header and still renders to
        # exactly one header line.
        body = "see the <!-- YOKE:STRATEGY-DOC ... --> reference\n"
        out = hdr.render_file_text("PAD", "2026-06-10T00:00:00Z", body)
        assert hdr.parse_file_text(out).body == body
