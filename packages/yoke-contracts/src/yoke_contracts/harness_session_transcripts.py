"""Where each harness keeps its local session transcripts, and how to scope them.

Onboarding an existing project reads earlier agent sessions for work that
never reached an issue or pull request. Those transcripts live in each
harness's own store on each machine, so the facts belong to the harness
rather than to a skill: the renderer copies each entry into
``runtime/harness/<harness_id>/manifest.json`` under ``session_transcripts``
(see ``runtime/harness/manifest-schema.md``) and agents read the manifest.

Each entry names the store, how one transcript is tied to a checkout, and
the evidence that established it. ``unverified`` is a first-class value: a
harness nobody has inspected says so rather than inheriting a neighbour's
layout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

TranscriptStoreClass = Literal["local_jsonl", "unverified"]


@dataclass(frozen=True)
class HarnessSessionTranscripts:
    """One harness family's local transcript store plus its evidence."""

    store: TranscriptStoreClass
    location: str
    project_match: str
    evidence: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)


HARNESS_SESSION_TRANSCRIPTS: dict[str, HarnessSessionTranscripts] = {
    "claude-code": HarnessSessionTranscripts(
        store="local_jsonl",
        location="~/.claude/projects/<checkout-key>/<session_id>.jsonl",
        project_match=(
            "<checkout-key> is the absolute checkout path with each non-ASCII-"
            "alphanumeric UTF-16 code unit replaced by '-'; keys over 200 units "
            "use the first 200 plus '-' and the base-36 absolute signed 32-bit "
            "hash of the original path (h = 31*h + charCode); one directory "
            "per checkout"
        ),
        evidence=(
            "yoke_harness.session_relay_claude_transcript derives the same "
            "key for stopped-session wake; read on claude-cli."
        ),
    ),
    "codex": HarnessSessionTranscripts(
        store="local_jsonl",
        location="~/.codex/sessions/YYYY/MM/DD/rollout-<started>-<session_id>.jsonl",
        project_match=(
            "the first line is a session_meta row whose payload.cwd names "
            "the directory the session ran in"
        ),
        evidence=(
            "Read on codex-cli: the rollout's first row is session_meta with "
            "cwd; yoke_contracts.harness_turn_record_capability reads the "
            "same files."
        ),
    ),
    "cursor": HarnessSessionTranscripts(
        store="local_jsonl",
        location=(
            "~/.cursor/projects/<checkout-slug>/agent-transcripts/<id>/<id>.jsonl"
        ),
        project_match=(
            "<checkout-slug> is yoke_contracts.harness_folder_trust."
            "cursor_project_slug(checkout): the absolute path with dots "
            "dropped and each non-alphanumeric run collapsed to '-'"
        ),
        evidence=(
            "yoke_contracts.cursor_session_map parses this layout and "
            "harness_folder_trust reproduces the slug, verified against "
            "entries Cursor wrote."
        ),
    ),
}


def session_transcripts_for_harness(harness_id: str) -> HarnessSessionTranscripts:
    """Return the declared store; an unknown harness says it is unverified."""
    known = HARNESS_SESSION_TRANSCRIPTS.get(harness_id)
    if known is not None:
        return known
    return HarnessSessionTranscripts(
        store="unverified",
        location="",
        project_match="",
        evidence=(
            f"No transcript store recorded for harness id {harness_id!r}. "
            "Add an inspected entry to yoke_contracts."
            "harness_session_transcripts.HARNESS_SESSION_TRANSCRIPTS before "
            "any surface tells an agent where this harness keeps transcripts."
        ),
    )


__all__ = (
    "HARNESS_SESSION_TRANSCRIPTS",
    "HarnessSessionTranscripts",
    "TranscriptStoreClass",
    "session_transcripts_for_harness",
)
