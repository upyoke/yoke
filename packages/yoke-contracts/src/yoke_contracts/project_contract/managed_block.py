"""The Yoke-managed Markdown block: markers, rendering, and extraction.

A managed block is the marker-delimited region ``yoke project install`` owns
inside a co-owned Markdown file (``AGENTS.md`` / ``CLAUDE.md`` / ``CODEX.md``).
The contract lives here, in the shared base package, because two sides need it
and must agree byte-for-byte:

* the **server** (``install_bundle.build_bundle``) extracts the block body from
  its own doctrine files to ship as the bundle's managed content, and
* the **client** (``yoke_cli.project_install.managed_markdown``) renders that
  body back into a managed project's files.

:func:`render_block` and :func:`extract_block_body` are inverses, so a block the
server extracts and the client re-renders round-trips to the identical bytes.
The markers are exact-string sentinels; the note is deliberately kept out of
them so re-wording the guidance never breaks block detection.
"""

from __future__ import annotations

from typing import Optional, Tuple

MANAGED_BLOCK_BEGIN = "<!-- BEGIN YOKE MANAGED BLOCK -->"
MANAGED_BLOCK_END = "<!-- END YOKE MANAGED BLOCK -->"
# Marks where the generated main-agent packet begins inside a managed block.
# The bundle appends the packet under this marker; a managed project's session
# hooks read the marker to decide whether the rules file already supplies the
# packet or whether they must deliver it themselves.
MAIN_AGENT_PACKET_MARKER = "<!-- YOKE MAIN-AGENT PACKET -->"
# Human-facing guidance rendered as the first line inside every block. Kept out
# of the marker strings themselves so block detection stays an exact-string
# search regardless of how the guidance is later reworded.
MANAGED_BLOCK_NOTE = (
    "<!-- Managed by `yoke project install`. Everything between the BEGIN and "
    "END markers is overwritten on refresh — do not edit it here. Your own "
    "content outside the markers is always preserved. -->"
)


def render_block(content: str) -> str:
    """Wrap block content in the begin/end markers plus the do-not-edit note."""
    body = content.strip("\n")
    return (
        f"{MANAGED_BLOCK_BEGIN}\n{MANAGED_BLOCK_NOTE}\n{body}\n"
        f"{MANAGED_BLOCK_END}"
    )


def block_span(text: str) -> Optional[Tuple[int, int]]:
    """Return (start, end) offsets of the managed block, or None if absent.

    ``start`` is the offset of the BEGIN marker; ``end`` is just past the END
    marker, so ``text[start:end]`` is the whole marked region.
    """
    start = text.find(MANAGED_BLOCK_BEGIN)
    if start == -1:
        return None
    end = text.find(MANAGED_BLOCK_END, start)
    if end == -1:
        return None
    return start, end + len(MANAGED_BLOCK_END)


def extract_block_body(text: str) -> Optional[str]:
    """Return the block's body — the inverse of :func:`render_block`.

    Strips the markers and the leading do-not-edit note, returning just the
    authored content. ``None`` when ``text`` carries no complete managed block.
    ``render_block(extract_block_body(render_block(x))) == render_block(x)``.
    """
    span = block_span(text)
    if span is None:
        return None
    start, end = span
    inner = text[start + len(MANAGED_BLOCK_BEGIN): end - len(MANAGED_BLOCK_END)]
    lines = inner.lstrip("\n").split("\n")
    if lines and lines[0] == MANAGED_BLOCK_NOTE:
        lines = lines[1:]
    return "\n".join(lines).strip("\n")


def carries_main_agent_packet(text: str) -> bool:
    """True when *text* already carries the generated main-agent packet.

    The install bundle composes the packet into the managed block, so a
    managed project's auto-loaded rules file normally supplies it to every
    session at no cost. A project installed before the packet shipped — or one
    whose server-side render degraded — has no marker, and its session hooks
    deliver the packet themselves rather than leaving the session without one.
    """
    return MAIN_AGENT_PACKET_MARKER in text


__all__ = [
    "MAIN_AGENT_PACKET_MARKER",
    "MANAGED_BLOCK_BEGIN",
    "MANAGED_BLOCK_END",
    "MANAGED_BLOCK_NOTE",
    "block_span",
    "carries_main_agent_packet",
    "extract_block_body",
    "render_block",
]
