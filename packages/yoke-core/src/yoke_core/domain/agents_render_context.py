"""Marker expansion for canonical agent prompts.

Canonical agent prompts (``runtime/agents/<role>.md``) carry packet
insertion markers of the form::

    <!-- YOKE:DB-PACKET role=<role> topic=<topic> start -->
    <!-- YOKE:DB-PACKET end -->

The renderer (:mod:`yoke_core.domain.agents_render`) calls
:func:`expand_markers` on the canonical body before wrapping it for the
Claude or Codex adapter, replacing whatever sits between each marker
pair with the freshly generated packet body from
:mod:`yoke_core.domain.schema_api_context`. The marker pairs survive
the expansion so the next render is idempotent and a drift check can
re-expand and compare.

Same expander runs for both Claude and Codex, which gives the byte-
identical packet bodies between marker pairs.
"""

from __future__ import annotations

import re

from yoke_core.domain import schema_api_context, schema_api_context_seed as seed


MARKER_START_RE = re.compile(
    r"<!-- YOKE:DB-PACKET role=(?P<role>[\w-]+) topic=(?P<topic>[\w-]+) start -->"
)
MARKER_END = "<!-- YOKE:DB-PACKET end -->"


class MarkerSyntaxError(ValueError):
    """Raised when canonical text contains a malformed or unmatched marker."""


def find_marker_pairs(text: str) -> list[dict]:
    """Return one entry per ``start`` / ``end`` marker pair in *text*.

    Each entry is a dict with keys ``role``, ``topic``,
    ``marker_start`` (offset of the ``<`` in the start marker),
    ``marker_start_end`` (offset just past the ``>`` of the start
    marker), ``marker_end_start`` (offset of the ``<`` in the end
    marker), and ``marker_end_end`` (offset just past the ``>`` of the
    end marker). Raises :class:`MarkerSyntaxError` for an unmatched
    start marker.
    """
    pairs: list[dict] = []
    pos = 0
    while True:
        m = MARKER_START_RE.search(text, pos)
        if m is None:
            return pairs
        end_idx = text.find(MARKER_END, m.end())
        if end_idx < 0:
            raise MarkerSyntaxError(
                f"unmatched start marker at offset {m.start()}: "
                f"role={m.group('role')} topic={m.group('topic')}"
            )
        pairs.append(
            {
                "role": m.group("role"),
                "topic": m.group("topic"),
                "marker_start": m.start(),
                "marker_start_end": m.end(),
                "marker_end_start": end_idx,
                "marker_end_end": end_idx + len(MARKER_END),
            }
        )
        pos = end_idx + len(MARKER_END)


def validate_marker_syntax(text: str) -> list[str]:
    """Return human-readable issues for malformed / unknown markers in *text*.

    Empty list means every start marker has a matching end marker, every
    role is in :data:`seed.ROLE_TOPICS`, every topic is in
    :data:`seed.TOPICS`, and there are no unmatched end markers. The
    renderer ``check`` command surfaces this list when present.
    """
    issues: list[str] = []
    try:
        pairs = find_marker_pairs(text)
    except MarkerSyntaxError as exc:
        return [str(exc)]
    for p in pairs:
        if p["role"] not in seed.ROLE_TOPICS:
            issues.append(
                f"unknown role at offset {p['marker_start']}: "
                f"role={p['role']}"
            )
        if p["topic"] not in seed.TOPICS:
            issues.append(
                f"unknown topic at offset {p['marker_start']}: "
                f"topic={p['topic']}"
            )
    paired_end_offsets = {p["marker_end_start"] for p in pairs}
    pos = 0
    while True:
        end_idx = text.find(MARKER_END, pos)
        if end_idx < 0:
            break
        if end_idx not in paired_end_offsets:
            issues.append(
                f"end marker at offset {end_idx} without matching start"
            )
        pos = end_idx + len(MARKER_END)
    return issues


def expand_markers(text: str) -> str:
    """Replace each marker pair's body with the freshly generated packet.

    The marker pair itself is preserved; only the content between the
    markers is replaced. Idempotent: calling :func:`expand_markers` on
    already-expanded text yields identical output.

    Raises :class:`MarkerSyntaxError` for an unmatched start marker. An
    unknown role or topic raises :class:`ValueError` from the underlying
    :func:`schema_api_context.render_topic_packet`.
    """
    pairs = find_marker_pairs(text)
    if not pairs:
        return text
    out: list[str] = []
    cursor = 0
    for p in pairs:
        out.append(text[cursor : p["marker_start_end"]])
        out.append("\n\n")
        out.append(schema_api_context.render_topic_packet(p["topic"]).rstrip("\n"))
        out.append("\n\n")
        cursor = p["marker_end_start"]
    out.append(text[cursor:])
    return "".join(out)


def detect_canonical_body_drift(text: str, source_label: str) -> list[str]:
    """Return drift descriptions for one canonical agent body.

    Walks two regression layers in order:

    1. Marker syntax (unmatched / unknown role / unknown topic).
    2. Stale-term coexistence: if the body carries valid packet markers,
       any :data:`schema_api_context_seed.STALE_TERMS` entry that also
       appears anywhere in the body is hand-authored content shadowing
       the generated packet. Skipped when marker syntax is
       broken — that drift is already surfaced.
    """
    issues = validate_marker_syntax(text)
    drift = [f"marker: {source_label}: {issue}" for issue in issues]
    if issues or not find_marker_pairs(text):
        return drift
    for stale in seed.STALE_TERMS:
        if stale in text:
            drift.append(
                f"stale-term: {source_label}: {stale!r} alongside packet "
                "markers"
            )
    return drift


def detect_packet_drift(text: str) -> list[str]:
    """Return drift descriptions when *text*'s marker bodies are stale.

    Empty list means every marker pair's body matches the freshly
    generated packet (the expander is a no-op). A non-empty list
    contains one descriptor per drifting pair plus any surfaced syntax
    issues.
    """
    issues = validate_marker_syntax(text)
    if issues:
        return issues
    expanded = expand_markers(text)
    if expanded == text:
        return []
    drift: list[str] = []
    for p in find_marker_pairs(text):
        on_disk = text[p["marker_start_end"] : p["marker_end_start"]]
        fresh = (
            "\n\n"
            + schema_api_context.render_topic_packet(p["topic"]).rstrip("\n")
            + "\n\n"
        )
        if on_disk != fresh:
            drift.append(
                f"packet body drift: role={p['role']} topic={p['topic']}"
            )
    if not drift:
        drift.append("packet body drift: expander output differs from input")
    return drift
