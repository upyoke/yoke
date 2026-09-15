"""One provider comparison entry is read whole, or not read at all."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.deployment_run_compare_response import recorded_commit

BASE = "a" * 40
TIP = "c" * 40


@pytest.mark.parametrize(
    "entry",
    [
        "not-an-object",
        {"parents": [{"sha": BASE}]},
        {"sha": "abc", "parents": [{"sha": BASE}]},
        {"sha": TIP, "commit": {}},
        {"sha": TIP, "commit": {}, "parents": []},
        {"sha": TIP, "commit": {}, "parents": [{"ref": "no-sha"}]},
        {"sha": TIP, "commit": {}, "parents": [{"sha": "garbage"}]},
        {"sha": TIP, "commit": {}, "parents": [{"sha": BASE[:8]}]},
        {"sha": TIP, "commit": {}, "parents": ["not-an-object"]},
    ],
    ids=[
        "entry-not-an-object",
        "sha-absent",
        "sha-unusable",
        "parents-absent",
        "parents-empty",
        "parent-without-sha",
        "parent-sha-not-hex",
        "parent-sha-abbreviated",
        "parent-not-an-object",
    ],
)
def test_a_commit_entry_that_cannot_carry_the_graph_is_unknown(entry: Any):
    """Skipping a malformed entry loses the fact that it was malformed.

    The first-parent walk and the attribution reachability both read parents,
    so an entry recorded without them truncates silently and the release reads
    as shorter rather than unread.
    """
    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        recorded_commit(entry)

    assert raised.value.reason == "repository_provider_comparison_incomplete"


def test_a_well_formed_entry_reads_into_one_graph_node():
    node = recorded_commit(
        {
            "sha": TIP,
            "commit": {
                "message": "Land it",
                "committer": {"date": "2026-09-15T00:00:00Z"},
            },
            "parents": [{"sha": BASE}],
        }
    )

    assert node == {
        TIP: {
            "message": "Land it",
            "committed_at": "2026-09-15T00:00:00Z",
            "parents": (BASE,),
        }
    }


def test_an_unreadable_first_parent_is_never_dropped_for_the_second():
    """Parent order is the whole meaning of a first-parent walk.

    Filtering the unreadable entry out promotes the second parent into first
    position, and the walk then follows a merged side branch as though it
    were the trunk — reporting a different release rather than an unread one.
    """
    with pytest.raises(CarriedWorkSourceUnavailable) as raised:
        recorded_commit(
            {
                "sha": TIP,
                "commit": {},
                "parents": [{"ref": "missing-sha"}, {"sha": BASE}],
            }
        )

    assert raised.value.reason == "repository_provider_comparison_incomplete"
    assert "position 0" in raised.value.recovery


def test_a_readable_parent_list_keeps_the_order_it_arrived_in():
    second = "d" * 40
    node = recorded_commit(
        {
            "sha": TIP,
            "commit": {},
            "parents": [{"sha": BASE}, {"sha": second}],
        }
    )

    assert node[TIP]["parents"] == (BASE, second)
