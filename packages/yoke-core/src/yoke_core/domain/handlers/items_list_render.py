"""Render projected item rows, actor labels and effective completion flows."""

from typing import Any, Dict, List

from yoke_core.domain.items_projection import ACTOR_LABEL_FIELDS, ITEM_INSTANT_FIELDS
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.item_completion_flow_projection import completion_flow_values

_UNSET_LABEL_TOKENS = frozenset({"none", "null"})

from yoke_core.domain.actors import ActorError  # noqa: E402

#: The degrade policy for actor-name cells: an unresolvable actor means
#: "cannot render" -> empty cell. One orphan actor must not fail the page.
_ACTOR_ERRORS = ActorError


def _actor_label_batches(
    conn: Any,
    fields: List[str],
    rows: list[tuple],
) -> dict[int, str]:
    """Resolve every distinct actor id on this page in one query.

    Returns ``{actor_id: label}``; ids that cannot be rendered degrade to
    an empty cell rather than failing the listing.
    """
    positions = [i for i, f in enumerate(fields) if f in ACTOR_LABEL_FIELDS]
    actor_ids: set[int] = set()
    for row in rows:
        for position in positions:
            raw = str(row[position] or "").strip()
            if not raw or raw.lower() in _UNSET_LABEL_TOKENS:
                continue
            try:
                actor_ids.add(int(raw))
            except ValueError:
                continue
    if not actor_ids:
        return {}
    ordered = sorted(actor_ids)
    markers = ", ".join("%s" for _ in ordered)
    by_actor: dict[int, list[Any]] = {}
    missing: set[int] = set(ordered)
    for actor_id, *label_parts in conn.execute(
        "SELECT a.id, NULLIF(a.name, '') AS name FROM actors a "
        f"WHERE a.id IN ({markers})",
        tuple(ordered),
    ).fetchall():
        missing.discard(int(actor_id))
        by_actor.setdefault(int(actor_id), []).extend(label_parts)
    resolved: dict[int, str] = {}
    for actor_id in ordered:
        labels = [
            str(label)
            for label in by_actor.get(actor_id, [])
            if label not in (None, "")
        ]
        if len(labels) == 1:
            resolved[actor_id] = labels[0]
            continue
        if len(labels) > 1:
            resolved[actor_id] = ""  # ambiguous display projection
            continue
        try:
            from yoke_core.domain.actors import actor_name

            resolved[actor_id] = actor_name(conn, actor_id)
        except _ACTOR_ERRORS:
            # Orphan/missing-label actor: degrade the cell, never the page.
            resolved[actor_id] = ""
    return resolved


def _render_rows(
    conn: Any,
    fields: List[str],
    rows: list[tuple],
) -> List[Dict[str, Any]]:
    """Project raw storage rows into operator-facing field maps.

    ``id`` renders the item's public ref (batched through
    :class:`ItemRefLookup`); actor-label fields resolve through one
    batched label query per page; clocks stay native/null through response
    ownership and other fields pass as text.
    Runs on the handler's already-open connection — no second connect.
    """
    from yoke_core.domain.item_ref_render import render_item_ref_lookup

    ref_position = fields.index("id") if "id" in fields else None
    internal_ids = (
        [int(row[ref_position]) for row in rows] if ref_position is not None else []
    )
    ref_lookup = (
        render_item_ref_lookup(conn, internal_ids) if ref_position is not None else None
    )
    labels = _actor_label_batches(conn, fields, rows)

    def _render_label(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text or text.lower() in _UNSET_LABEL_TOKENS:
            return ""
        try:
            actor_id = int(text)
        except ValueError:
            return text
        return labels.get(actor_id, "")

    flows = (
        completion_flow_values(conn, [int(row[-1]) for row in rows])
        if "deployment_flow" in fields
        else {}
    )
    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        rendered: Dict[str, Any] = {}
        for position, field in enumerate(fields):
            value = row[position]
            if position == ref_position:
                rendered[field] = ref_lookup(int(value))
            elif field == "deployment_flow":
                rendered[field] = flows.get(
                    int(row[-1]), {"value": "", "source": "none"}
                )
            elif field in ACTOR_LABEL_FIELDS:
                rendered[field] = _render_label(value)
            elif field in ITEM_INSTANT_FIELDS:
                rendered[field] = None if value is None else parse_instant(value)
            else:
                rendered[field] = "" if value is None else str(value)
        out_rows.append(rendered)
    return out_rows
