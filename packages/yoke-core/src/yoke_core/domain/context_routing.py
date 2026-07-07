"""Project-level context routing accessor.

The ``context_routing`` Project Structure family stores project-wide
context-routing entries: the reserved ``entry_key="always"`` is the
project-wide always-included docs; any other ``entry_key`` is a topic name
whose docs are added when that topic matches.

Each entry's payload is ``{"docs": [str, ...]}`` — a non-empty list of
project-relative file path strings.

This module is the read/write surface for operators and other domains that
need context routing without speaking Project Structure's op list
vocabulary. It does not cache; every read hits the aggregate.

CLI usage::

    python3 -m yoke_core.domain.context_routing get-always <project-id>
    python3 -m yoke_core.domain.context_routing get-topic  <project-id> <topic>
    python3 -m yoke_core.domain.context_routing list-topics <project-id>
    python3 -m yoke_core.domain.context_routing set-always <project-id> <doc1> [<doc2> ...]
    python3 -m yoke_core.domain.context_routing set-topic  <project-id> <topic> <doc1> [<doc2> ...]
    python3 -m yoke_core.domain.context_routing clear-topic <project-id> <topic>

``get-always`` prints one doc per line and exits 0 when entries exist; it
prints nothing and exits 1 when no entry is configured. ``get-topic`` does
the same for a named topic. ``list-topics`` prints one topic name per line
(excluding the reserved ``always`` key) and always exits 0.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

from yoke_core.domain import project_structure as ps
from yoke_core.domain.project_structure import CONTEXT_ROUTING_ALWAYS_KEY


FAMILY = "context_routing"


def _read_entries(
    project_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Return ``{entry_key: [docs]}`` for every context_routing entry."""
    slice_ = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    out: Dict[str, List[str]] = {}
    for entry in slice_.get("entries") or []:
        key = entry.get("entry_key") or ""
        if not key:
            continue
        payload = entry.get("payload") or {}
        docs = payload.get("docs")
        if isinstance(docs, list):
            normalized = [d for d in docs if isinstance(d, str) and d]
            if normalized:
                out[key] = normalized
    return out


def get_always_docs(
    project_id: str,
    db_path: Optional[str] = None,
) -> List[str]:
    """Return the project-wide always-included docs, or an empty list."""
    entries = _read_entries(project_id, db_path=db_path)
    return list(entries.get(CONTEXT_ROUTING_ALWAYS_KEY, []))


def get_topic_docs(
    project_id: str,
    topic: str,
    db_path: Optional[str] = None,
) -> List[str]:
    """Return the docs for ``topic`` (excluding the reserved ``always`` key)."""
    if topic == CONTEXT_ROUTING_ALWAYS_KEY:
        return []
    entries = _read_entries(project_id, db_path=db_path)
    return list(entries.get(topic, []))


def list_topics(
    project_id: str,
    db_path: Optional[str] = None,
) -> List[str]:
    """Return the topic names (excluding the reserved ``always`` key), sorted."""
    entries = _read_entries(project_id, db_path=db_path)
    return sorted(k for k in entries if k != CONTEXT_ROUTING_ALWAYS_KEY)


def get_topic_map(
    project_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Return ``{topic: [docs]}`` for non-``always`` entries."""
    entries = _read_entries(project_id, db_path=db_path)
    return {k: v for k, v in entries.items() if k != CONTEXT_ROUTING_ALWAYS_KEY}


def set_entry(
    project_id: str,
    entry_key: str,
    docs: List[str],
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> None:
    """Upsert a context_routing entry for ``entry_key``."""
    if not isinstance(entry_key, str) or not entry_key:
        raise ValueError("entry_key must be a non-empty string")
    if not isinstance(docs, list) or not docs:
        raise ValueError("docs must be a non-empty list of strings")
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "put",
            "family": FAMILY,
            "attachment": "project",
            "entry_key": entry_key,
            "payload": {"docs": list(docs)},
        }],
        actor=actor,
        db_path=db_path,
    )


def clear_entry(
    project_id: str,
    entry_key: str,
    db_path: Optional[str] = None,
    actor: Optional[str] = None,
) -> bool:
    """Remove the context_routing entry for ``entry_key``.

    Returns ``True`` when an entry was removed, ``False`` when no entry
    existed — so callers can differentiate "already empty" from "removed".
    """
    state = ps.read_structure(project_id, family=FAMILY, db_path=db_path)
    present = any(
        (entry.get("entry_key") or "") == entry_key
        for entry in (state.get("entries") or [])
    )
    if not present:
        return False
    ps.apply_patch(
        project_id,
        ops=[{
            "op": "remove",
            "family": FAMILY,
            "attachment": "project",
            "entry_key": entry_key,
        }],
        actor=actor,
        db_path=db_path,
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_get_always(args: argparse.Namespace) -> int:
    docs = get_always_docs(args.project_id)
    if not docs:
        return 1
    for doc in docs:
        print(doc)
    return 0


def _cmd_get_topic(args: argparse.Namespace) -> int:
    docs = get_topic_docs(args.project_id, args.topic)
    if not docs:
        return 1
    for doc in docs:
        print(doc)
    return 0


def _cmd_list_topics(args: argparse.Namespace) -> int:
    for topic in list_topics(args.project_id):
        print(topic)
    return 0


def _cmd_set_always(args: argparse.Namespace) -> int:
    try:
        set_entry(
            args.project_id, CONTEXT_ROUTING_ALWAYS_KEY, args.docs, actor=args.actor,
        )
    except (ValueError, ps.ProjectStructureError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Set context_routing always for '{args.project_id}' -> {len(args.docs)} doc(s)")
    return 0


def _cmd_set_topic(args: argparse.Namespace) -> int:
    if args.topic == CONTEXT_ROUTING_ALWAYS_KEY:
        print(
            f"Error: topic name '{CONTEXT_ROUTING_ALWAYS_KEY}' is reserved; "
            f"use 'set-always' to write the project-wide entry.",
            file=sys.stderr,
        )
        return 1
    try:
        set_entry(args.project_id, args.topic, args.docs, actor=args.actor)
    except (ValueError, ps.ProjectStructureError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Set context_routing topic '{args.topic}' for '{args.project_id}' -> "
        f"{len(args.docs)} doc(s)"
    )
    return 0


def _cmd_clear_topic(args: argparse.Namespace) -> int:
    try:
        removed = clear_entry(args.project_id, args.topic, actor=args.actor)
    except ps.ProjectStructureError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if removed:
        print(f"Cleared context_routing topic '{args.topic}' for '{args.project_id}'")
    else:
        print(
            f"No context_routing entry to clear for topic '{args.topic}' "
            f"in '{args.project_id}'"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.context_routing",
        description="Read and write the project-level context routing entries.",
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_ga = sub.add_parser("get-always", help="Print the project-wide always-included docs")
    p_ga.add_argument("project_id")

    p_gt = sub.add_parser("get-topic", help="Print docs for a topic")
    p_gt.add_argument("project_id")
    p_gt.add_argument("topic")

    p_lt = sub.add_parser("list-topics", help="Print configured topic names")
    p_lt.add_argument("project_id")

    p_sa = sub.add_parser("set-always", help="Upsert the project-wide always-included docs")
    p_sa.add_argument("project_id")
    p_sa.add_argument("docs", nargs="+")
    p_sa.add_argument("--actor")

    p_st = sub.add_parser("set-topic", help="Upsert docs for a topic")
    p_st.add_argument("project_id")
    p_st.add_argument("topic")
    p_st.add_argument("docs", nargs="+")
    p_st.add_argument("--actor")

    p_ct = sub.add_parser("clear-topic", help="Remove the entry for a topic")
    p_ct.add_argument("project_id")
    p_ct.add_argument("topic")
    p_ct.add_argument("--actor")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.subcmd:
        parser.print_help(sys.stderr)
        return 2
    dispatch = {
        "get-always": _cmd_get_always,
        "get-topic": _cmd_get_topic,
        "list-topics": _cmd_list_topics,
        "set-always": _cmd_set_always,
        "set-topic": _cmd_set_topic,
        "clear-topic": _cmd_clear_topic,
    }
    return dispatch[args.subcmd](args)


if __name__ == "__main__":
    sys.exit(main())
