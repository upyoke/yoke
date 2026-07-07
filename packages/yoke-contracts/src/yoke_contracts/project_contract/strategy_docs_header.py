"""Idempotent render header for the tracked ``.yoke/strategy/`` views.

Every rendered ``.yoke/strategy/<slug>.md`` begins with exactly one
machine-parseable HTML-comment line carrying the slug, the DB row's
``updated_at``, and the sha256 of the content body (header line
excluded, byte-precise), plus a one-sentence notice that the DB is
authoritative and edits write back via ``yoke strategy ingest``.

The header NEVER embeds render wall-clock time: a render of unchanged
DB content is byte-identical to the previous render, so tracked files
produce no git diff (the ``docs/atlas.md`` precedent).

``yoke strategy ingest`` parses this header as its compare-and-swap
base marker: ``updated_at`` is the CAS guard against lost updates and
``content_sha256`` is the unchanged-file fast path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

HEADER_MARKER = "<!-- YOKE:STRATEGY-DOC "

_HEADER_RE = re.compile(
    r"^<!-- YOKE:STRATEGY-DOC slug=(?P<slug>[A-Za-z0-9_-]+) "
    r"updated_at=(?P<updated_at>\S+) "
    # Optional: the resolved actor label of the last editor. Absent on
    # pre-feature headers and when the editing actor has no label, so old
    # files keep parsing. Display-only — NOT part of the CAS base (updated_at)
    # or the content hash.
    r"(?:updated_by=(?P<updated_by>\S+) )?"
    r"content_sha256=(?P<sha>[0-9a-f]{64}) "
    r"(?P<notice>.+?) -->$"
)


class StrategyHeaderError(ValueError):
    """Raised when a strategy file's render header is missing or mangled."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        # Parse failures: ``missing`` (no header line at all) vs
        # ``mangled`` (marker present but unparseable). Replace
        # normalization failure: ``slug_mismatch`` (a rendered file for one
        # slug was supplied as another slug's replacement). Render failure:
        # ``content_has_header`` (the body handed to render already begins
        # with a header — would stack a second one). All name the file.
        self.kind = kind


@dataclass(frozen=True)
class StrategyDocHeader:
    """Parsed header fields plus the byte-precise body that follows."""

    slug: str
    updated_at: str
    content_sha256: str
    body: str
    # Resolved actor label of the last editor (display-only); None on
    # pre-feature headers or when the editing actor has no label.
    updated_by: str | None = None


def content_sha256(content: str) -> str:
    """Return the canonical sha256 hex digest of one doc body."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def header_notice(slug: str) -> str:
    """One-sentence DB-is-authoritative notice embedded in the header."""
    return (
        "The Yoke DB is authoritative for this doc: edit the file, "
        f"then write back with `yoke strategy ingest {slug}`."
    )


def build_header_line(
    slug: str,
    updated_at: str,
    content: str,
    *,
    updated_by: str | None = None,
) -> str:
    """Build the single header line for one rendered strategy doc.

    Deterministic for a given ``(slug, updated_at, updated_by, content)`` —
    no wall-clock input — which is what makes renders byte-idempotent.
    ``updated_by`` is the resolved actor label of the last editor; it is
    emitted only when truthy (no label → field omitted) so it never reads
    as a misleading sentinel, and it is display-only — never the CAS base.
    """
    by = f"updated_by={updated_by} " if updated_by else ""
    return (
        f"<!-- YOKE:STRATEGY-DOC slug={slug} "
        f"updated_at={updated_at} "
        f"{by}"
        f"content_sha256={content_sha256(content)} "
        f"{header_notice(slug)} -->"
    )


def render_file_text(
    slug: str,
    updated_at: str,
    content: str,
    *,
    updated_by: str | None = None,
) -> str:
    """Return the full rendered file: header line + newline + body.

    Refuses ``content`` that already begins with a render header. The DB
    ``content`` column holds header-free body, so prepending a fresh
    header onto an already-rendered file would stack two headers — the
    double-header corruption that makes every strategy view show as
    git-modified. A header-included column is itself a corruption signal,
    so this fails loud (``kind="content_has_header"``) rather than
    silently double-heading.
    """
    if content.startswith(HEADER_MARKER):
        raise StrategyHeaderError(
            f"refusing to render '{slug}': content already begins with a "
            f"'{HEADER_MARKER.strip()}' header — the DB content column must "
            "hold header-free body, not a rendered file",
            kind="content_has_header",
        )
    return (
        build_header_line(slug, updated_at, content, updated_by=updated_by)
        + "\n"
        + content
    )


def parse_file_text(file_text: str) -> StrategyDocHeader:
    """Split one rendered file into its parsed header and byte-precise body.

    The body is everything after the header line's terminating newline,
    unmodified — ``content_sha256(parsed.body)`` reproduces the hash a
    fresh render of the same content would embed.

    Raises :class:`StrategyHeaderError` with ``kind='missing'`` when the
    first line is not a strategy header at all, and ``kind='mangled'``
    when the marker is present but the line does not parse (or the file
    has no body separator).
    """
    first_line, sep, body = file_text.partition("\n")
    if not first_line.startswith(HEADER_MARKER):
        raise StrategyHeaderError(
            "first line is not a YOKE:STRATEGY-DOC render header",
            kind="missing",
        )
    match = _HEADER_RE.match(first_line)
    if match is None or not sep:
        raise StrategyHeaderError(
            "YOKE:STRATEGY-DOC header line is mangled (expected "
            "slug=... updated_at=... content_sha256=<64 hex> notice -->)",
            kind="mangled",
        )
    return StrategyDocHeader(
        slug=match.group("slug"),
        updated_at=match.group("updated_at"),
        content_sha256=match.group("sha"),
        body=body,
        updated_by=match.group("updated_by"),
    )


def strip_render_header_if_present(
    content: str,
    *,
    expected_slug: str | None = None,
) -> str:
    """Return header-free body when ``content`` is a rendered strategy file.

    ``strategy.doc.replace`` accepts operator-authored replacement text. In
    practice, the most ergonomic content file is often the rendered
    ``.yoke/strategy/<slug>.md`` view, whose first line is the generated
    strategy header. This helper makes that path idempotent by stripping exactly
    one well-formed generated header when present.

    Plain header-free content is returned unchanged. A mangled generated header
    still raises :class:`StrategyHeaderError`, and ``expected_slug`` protects
    callers from accidentally replacing one doc with another doc's rendered
    file.
    """
    if not content.startswith(HEADER_MARKER):
        return content
    parsed = parse_file_text(content)
    if expected_slug is not None and parsed.slug != expected_slug:
        raise StrategyHeaderError(
            f"rendered strategy header slug {parsed.slug!r} does not match "
            f"target doc {expected_slug!r}",
            kind="slug_mismatch",
        )
    return parsed.body


__all__ = [
    "HEADER_MARKER",
    "StrategyDocHeader",
    "StrategyHeaderError",
    "build_header_line",
    "content_sha256",
    "header_notice",
    "parse_file_text",
    "render_file_text",
    "strip_render_header_if_present",
]
