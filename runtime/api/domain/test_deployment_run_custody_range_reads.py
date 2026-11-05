"""Custody answers merged landings from one range comparison per project.

Asking the repository provider whether the candidate contains each merged
item's landing cost up to three GitHub reads per item. One comparison since
the previous release lists every landing the candidate added, so composition
pays per project, not per item, and reaches the same verdict.
"""

from __future__ import annotations

import collections
import functools
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.deployment_run_source_reads_once_test_support import _release
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CARRIER_ITEM_ID,
    CONSUMER_ITEM_ID,
)
from runtime.api.fixtures.carried_release_candidate import (
    git,
    insert_run,
    item_ref,
    record_landing_receipt,
)
from yoke_core.domain import deployment_run_unheld_candidates as unheld
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

MERGED_ITEM_IDS = tuple(range(9701, 9706))
PER_ITEM_READS = ("contains_commit", "adds_nothing")


def _land_items(conn: Any, repo: Path) -> str:
    """Land several more carrier items after the previous release."""
    for item_id in MERGED_ITEM_IDS:
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="blitz",
            status="implementing",
            deployment_flow=CARRIER_FLOW,
        )
        conn.commit()
        (repo / f"item-{item_id}.txt").write_text(f"{item_id}\n", encoding="utf-8")
        git(repo, "add", f"item-{item_id}.txt")
        git(repo, "commit", "-m", f"Land item {item_id}")
        record_landing_receipt(
            conn,
            item_id,
            branch=item_ref(conn, item_id),
            tip=git(repo, "rev-parse", "HEAD"),
        )
    # Custody walks landed items only; the receipts above are their landings.
    conn.execute(
        "UPDATE items SET merged_at=%s WHERE id = ANY(%s)",
        ("2026-09-14T02:00:00Z", [CARRIER_ITEM_ID, CONSUMER_ITEM_ID, *MERGED_ITEM_IDS]),
    )
    conn.commit()
    return git(repo, "rev-parse", "HEAD")


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for name in ("commit_range", *PER_ITEM_READS):
        original = getattr(LocalCheckoutSource, name)

        def counted(self, *args: Any, _name=name, _original=original, **kwargs: Any):
            counts[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(
            LocalCheckoutSource, name, functools.wraps(original)(counted)
        )
    return counts


def _compose(conn: Any) -> tuple[bool, str, set[int]]:
    valid, message = cmd_validate_composition(
        "run-candidate", connection=conn, require_item_qa_members=False
    )
    members = {
        int(row[0])
        for row in conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate'"
        ).fetchall()
    }
    conn.rollback()
    return valid, message, members


def test_composition_reads_one_range_per_project_whatever_the_item_count(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    lineage = _land_items(test_db, release["carrier_repo"])
    insert_run(
        test_db, "run-candidate", lineage=lineage, status="created", flow=CARRIER_FLOW
    )
    counts = _count_reads(monkeypatch)

    ranged = _compose(test_db)

    # Two projects ship: custody and carried work each compare once per
    # project, and no merged item asks the source on its own.
    assert counts["commit_range"] == 4
    assert sum(counts[name] for name in PER_ITEM_READS) == 0
    assert set(MERGED_ITEM_IDS) <= ranged[2]

    counts.clear()
    monkeypatch.setattr(
        unheld, "candidate_range_commits", lambda *_args, **_kwargs: frozenset()
    )
    per_item = _compose(test_db)

    assert counts["contains_commit"] >= len(MERGED_ITEM_IDS)
    assert per_item == ranged
