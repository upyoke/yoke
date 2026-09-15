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
    ],
    ids=[
        "entry-not-an-object",
        "sha-absent",
        "sha-unusable",
        "parents-absent",
        "parents-empty",
        "parents-without-shas",
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
