"""Every stored section ordering reaches the body, on one side or the other.

The two rendering groups used to cover a window rather than partition the
line: below zero and at or past the unset sentinel fell outside both, so a
section could be written, stored, and read back from ``item_sections`` while
appearing nowhere in ``items.body``. Nothing refused those writes, which is
what made the gap quiet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.render_body_test_helpers import (
    _connect,
    _init_db,
    _p,
    _seed_item,
)
from yoke_core.domain import render_body
from yoke_core.domain.render_body_item_sections import (
    EARLY_ITEM_SECTION_ORDERING_LIMIT,
    UNSET_ITEM_SECTION_ORDERING,
)


_ITEM_ID = 11


def _add_section(conn, name: str, ordering: int | None) -> None:
    p = _p(conn)
    conn.execute(
        f"""
        INSERT INTO item_sections
            (item_id, section_name, content, ordering, source,
             created_at, updated_at)
        VALUES ({p}, {p}, {p}, {p}, 'operator',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        (_ITEM_ID, name, f"Body of {name}.", ordering),
    )
    conn.commit()


def _body_with(tmp_path: Path, sections: list[tuple[str, int | None]]) -> str:
    with _init_db(tmp_path) as db_path:
        conn = _connect(db_path)
        try:
            _seed_item(conn, _ITEM_ID, "Ordering item")
            for name, ordering in sections:
                _add_section(conn, name, ordering)
            return render_body.build_body(conn, _ITEM_ID) or ""
        finally:
            conn.close()


def _heading_order(body: str, names: list[str]) -> list[str]:
    positions = [
        (body.index(f"## {name}"), name) for name in names if f"## {name}" in body
    ]
    return [name for _position, name in sorted(positions)]


@pytest.mark.parametrize(
    "ordering",
    [
        -1000,
        -1,
        0,
        1,
        EARLY_ITEM_SECTION_ORDERING_LIMIT - 1,
        EARLY_ITEM_SECTION_ORDERING_LIMIT,
        EARLY_ITEM_SECTION_ORDERING_LIMIT + 1,
        UNSET_ITEM_SECTION_ORDERING,
        UNSET_ITEM_SECTION_ORDERING + 1,
        10_000_000,
        None,
    ],
    ids=[
        "far-negative", "negative-one", "zero", "one", "just-below-boundary",
        "at-boundary", "just-above-boundary", "at-unset-sentinel",
        "past-unset-sentinel", "far-past-sentinel", "null",
    ],
)
def test_any_accepted_ordering_reaches_the_body(
    tmp_path: Path, ordering: int | None,
) -> None:
    body = _body_with(tmp_path, [("Solo", ordering)])

    assert "## Solo" in body
    assert body.count("## Solo") == 1


def test_the_boundary_decides_which_group_a_section_lands_in(
    tmp_path: Path,
) -> None:
    """Below the boundary renders early, at or above it renders late.

    The spec fields between them are what make the two groups observable:
    an early section precedes the rendered spec and a late one follows it.
    """
    body = _body_with(
        tmp_path,
        [
            ("Below", EARLY_ITEM_SECTION_ORDERING_LIMIT - 1),
            ("AtBoundary", EARLY_ITEM_SECTION_ORDERING_LIMIT),
        ],
    )

    assert body.index("## Below") < body.index("## AtBoundary")


def test_a_negative_ordering_sorts_ahead_of_the_early_sections(
    tmp_path: Path,
) -> None:
    body = _body_with(
        tmp_path, [("First", -5), ("Second", 0), ("Third", 200)],
    )

    assert _heading_order(body, ["First", "Second", "Third"]) == [
        "First", "Second", "Third",
    ]


def test_orderings_past_the_sentinel_sort_after_the_unset_ones(
    tmp_path: Path,
) -> None:
    """NULL keeps its unset position, and a larger stored value follows it."""
    body = _body_with(
        tmp_path,
        [
            ("Numbered", EARLY_ITEM_SECTION_ORDERING_LIMIT + 1),
            ("Unset", None),
            ("Enormous", UNSET_ITEM_SECTION_ORDERING + 1),
        ],
    )

    assert _heading_order(body, ["Numbered", "Unset", "Enormous"]) == [
        "Numbered", "Unset", "Enormous",
    ]


@pytest.mark.parametrize(
    "ordering",
    [10, EARLY_ITEM_SECTION_ORDERING_LIMIT + 10],
    ids=["early-group", "late-group"],
)
def test_equal_orderings_break_ties_by_section_name(
    tmp_path: Path, ordering: int,
) -> None:
    body = _body_with(
        tmp_path,
        [("Beta", ordering), ("Alpha", ordering), ("Gamma", ordering)],
    )

    assert _heading_order(body, ["Alpha", "Beta", "Gamma"]) == [
        "Alpha", "Beta", "Gamma",
    ]


def test_a_section_at_the_sentinel_sorts_beside_an_unset_one(
    tmp_path: Path,
) -> None:
    """A stored sentinel value is indistinguishable from NULL by design.

    Both coalesce to the same number, so the section name is what separates
    them — the one property that keeps the order stable rather than
    arbitrary.
    """
    body = _body_with(
        tmp_path,
        [("Zulu", UNSET_ITEM_SECTION_ORDERING), ("Alpha", None)],
    )

    assert _heading_order(body, ["Alpha", "Zulu"]) == ["Alpha", "Zulu"]
