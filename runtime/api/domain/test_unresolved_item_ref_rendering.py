"""Visible output names an item by its public ref or says it has none.

``items.id`` and ``items.project_sequence`` are independent counters, so a
ref built from an internal id is not merely unhelpful — it names whichever
*other* item owns that number. These tests pin both halves of the rule: a
resolvable id renders its own project's prefix and sequence, and an id that
resolves to nothing renders a self-describing phrase instead of a ref.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_contracts.public_ref import format_item_ref, unresolved_item_ref

from yoke_core.domain.item_ref_render import ItemRefLookup, render_item_refs
from yoke_core.domain.project_identity import render_item_ref

from runtime.api.frontier_test_helpers import insert_item, make_test_db


# The external project's sequence deliberately differs from its internal id,
# and collides with a *different* item's internal id, which is exactly the
# shape a fabricated ref gets wrong.
EXTERNAL_INTERNAL_ID = 3273
EXTERNAL_SEQUENCE = 1896
COLLIDING_INTERNAL_ID = 1896


def _seed(conn) -> None:
    insert_item(
        conn,
        EXTERNAL_INTERNAL_ID,
        project="externalwebapp",
        project_sequence=EXTERNAL_SEQUENCE,
    )
    insert_item(conn, COLLIDING_INTERNAL_ID, project="yoke")
    conn.commit()


def test_render_uses_the_items_own_project_prefix_and_sequence():
    conn = make_test_db()
    _seed(conn)

    assert render_item_ref(conn, EXTERNAL_INTERNAL_ID) == (
        f"EXT-{EXTERNAL_SEQUENCE}"
    )


def test_render_never_reads_an_internal_id_as_a_sequence():
    """A fabricated ref would have named the colliding yoke item."""
    conn = make_test_db()
    _seed(conn)

    rendered = render_item_ref(conn, EXTERNAL_INTERNAL_ID)

    assert str(EXTERNAL_INTERNAL_ID) not in rendered
    assert rendered != f"YOK-{EXTERNAL_INTERNAL_ID}"
    assert rendered != render_item_ref(conn, COLLIDING_INTERNAL_ID)


def test_unresolvable_id_renders_a_phrase_rather_than_a_ref():
    conn = make_test_db()
    _seed(conn)
    missing = EXTERNAL_INTERNAL_ID + COLLIDING_INTERNAL_ID

    rendered = render_item_ref(conn, missing)

    assert rendered == unresolved_item_ref(missing)
    assert "unresolved item ref" in rendered
    assert "no project identity row" in rendered
    assert not rendered.startswith("YOK-")


def test_unresolved_phrase_cannot_be_mistaken_for_a_ref():
    """The phrase is bracketed so nothing round-trips it as a token."""
    phrase = unresolved_item_ref(7)

    assert phrase.startswith("<") and phrase.endswith(">")
    assert "-7" not in phrase


def test_an_unread_lookup_says_so_instead_of_naming_a_row():
    consulted = ItemRefLookup({}, consulted=True)
    unread = ItemRefLookup({}, consulted=False)

    assert "no project identity row" in consulted(EXTERNAL_INTERNAL_ID)
    assert "no control-plane read" in unread(EXTERNAL_INTERNAL_ID)
    assert str(EXTERNAL_INTERNAL_ID) not in unread(EXTERNAL_INTERNAL_ID).split(
        "items.id "
    )[0]


def test_batch_render_omits_rows_without_their_own_sequence():
    conn = make_test_db()
    _seed(conn)
    conn.execute(
        "UPDATE items SET project_sequence = NULL WHERE id = %s",
        (EXTERNAL_INTERNAL_ID,),
    )
    conn.commit()

    refs = render_item_refs(conn, [EXTERNAL_INTERNAL_ID, COLLIDING_INTERNAL_ID])

    assert EXTERNAL_INTERNAL_ID not in refs
    assert COLLIDING_INTERNAL_ID in refs


def test_format_refuses_to_borrow_a_number_for_a_missing_sequence():
    assert format_item_ref("externalwebapp", "EXT", None) == unresolved_item_ref()
    assert format_item_ref("externalwebapp", "EXT", EXTERNAL_SEQUENCE) == (
        f"EXT-{EXTERNAL_SEQUENCE}"
    )
