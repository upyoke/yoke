"""Immutable comparisons are shared across report passes; unknowns retry."""

from types import SimpleNamespace

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import insert_run
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain import delivery_landing_custody as custody
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.steering_fleet_report_landed_open import landed_without_closeout


def _provider(monkeypatch, *, status="behind", repo="owner/cache-tests"):
    calls = []
    opens = []

    def request(request, *, token):
        calls.append(request.path)
        return SimpleNamespace(
            body={
                "status": status(request.path) if callable(status) else status,
                "files": [
                    {"filename": "changed", "status": "modified", "sha": "e" * 40}
                ],
                "commits": [],
                "total_commits": 1,
            }
        )

    def open_source():
        opens.append(repo)
        return provider.RepositoryProviderSource(repo, "token")

    monkeypatch.setattr(provider, "request_with_retry", request)
    monkeypatch.setattr(
        containment, "carried_work_sources", lambda conn, project_id: (open_source,)
    )
    return calls, opens


@pytest.mark.parametrize(
    "status, state",
    [("behind", containment.CONTAINED), ("ahead", containment.NOT_CONTAINED)],
)
def test_definite_answers_survive_new_comparison_objects(monkeypatch, status, state):
    calls, opens = _provider(monkeypatch, status=status)
    for _ in range(2):
        assert (
            containment.candidate_contains_commit(
                None, 1, candidate_lineage="a" * 40, commit_sha="b" * 40
            ).state
            == state
        )
    assert len(calls) == 1
    assert len(opens) == 2  # Authority is checked before using cached facts.


def test_cache_separates_repositories_and_commit_pairs(monkeypatch):
    calls, _ = _provider(monkeypatch)
    for candidate, merge in [("a", "b"), ("c", "b"), ("a", "d")]:
        containment.candidate_contains_commit(
            None, 1, candidate_lineage=candidate * 40, commit_sha=merge * 40
        )
    assert len(calls) == 3
    calls, _ = _provider(monkeypatch, status="ahead", repo="other/repository")
    assert (
        containment.candidate_contains_commit(
            None, 1, candidate_lineage="a" * 40, commit_sha="b" * 40
        ).state
        == containment.NOT_CONTAINED
    )
    assert len(calls) == 1


def test_unknowns_and_source_refusals_are_retried(monkeypatch):
    class Source:
        origin = "repository_provider"
        location = "owner/unknown"
        attempts = 0

        def resolve_commit(self, ref):
            return ref

        def contains_commit(self, candidate, merge):
            self.attempts += 1
            if self.attempts == 1:
                raise containment.CarriedWorkSourceUnavailable("offline", "Retry.")
            return self.attempts >= 3

        def adds_nothing(self, candidate, merge):
            return None

    source = Source()
    monkeypatch.setattr(
        containment, "carried_work_sources", lambda conn, project_id: (lambda: source,)
    )
    states = [
        containment.candidate_contains_commit(
            None, 1, candidate_lineage="a" * 40, commit_sha="b" * 40
        ).state
        for _ in range(4)
    ]
    assert states == [
        containment.UNDETERMINED,
        containment.UNDETERMINED,
        containment.CONTAINED,
        containment.CONTAINED,
    ]
    assert source.attempts == 3


def test_cache_is_bounded(monkeypatch):
    from yoke_core.domain import repository_compare_pages

    monkeypatch.setattr(containment, "CACHE_LIMIT", 2)
    # Keep no comparison pages, so an evicted verdict is asked again.
    monkeypatch.setattr(repository_compare_pages, "PAGE_LIMIT", 0)
    calls, _ = _provider(monkeypatch)
    for merge in ("b", "c", "d", "b"):
        containment.candidate_contains_commit(
            None, 1, candidate_lineage="a" * 40, commit_sha=merge * 40
        )
    assert len(calls) == 4
    assert len(containment._VERDICTS) == 2


def test_report_pass_reuses_candidates_and_batches_landing_receipts(
    test_db, monkeypatch
):
    calls, opens = _provider(
        monkeypatch, status=lambda path: "ahead" if "a" * 40 in path else "behind"
    )
    item_ids = list(range(9700, 9724))
    for run_id in ("older", "newer"):
        insert_run(
            test_db,
            run_id,
            lineage=("a" if run_id == "newer" else "c") * 40,
            status="executing",
            flow="cache-flow",
        )
    for item_id in item_ids:
        insert_item(
            test_db,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="release",
            merged_at="2026-09-14T00:10:00Z",
        )
        record_entry(
            test_db,
            item_id=item_id,
            branch=f"lane-{item_id}",
            target="main",
            merge_sha=f"{item_id:040x}",
        )
        for run_id in ("older", "newer"):
            test_db.execute(
                "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
                "VALUES (%s,%s,%s)",
                (
                    run_id,
                    item_id,
                    "2026-09-14T00:30:00Z"
                    if run_id == "newer"
                    else "2026-09-14T00:20:00Z",
                ),
            )
    test_db.commit()

    class ReadCounter:
        receipt_reads = 0

        def __getattr__(self, key):
            return getattr(test_db, key)

        def execute(self, sql, params=()):
            if "SELECT item_id, content FROM item_sections" in sql:
                self.receipt_reads += 1
            return test_db.execute(sql, params)

    conn = ReadCounter()
    for _ in range(2):
        rows = landed_without_closeout(
            conn, project_id=1, now="2026-09-15T00:00:00Z", holders=()
        )
        assert {row.item_id for row in rows} == set(item_ids)
        assert all(row.custody_state == custody.HELD for row in rows)
    assert len(calls) == 2 * len(item_ids)
    assert len(opens) == 4  # Two candidates per pass, shared by every item.
    assert conn.receipt_reads == 2


def test_batched_receipts_keep_merge_precedence_and_ignore_malformed(monkeypatch):
    monkeypatch.setattr(
        custody,
        "read_json_sections",
        lambda *args, **kwargs: {
            1: {
                "receipts": {
                    "older": {
                        "updated_at": "2026-09-14T00:00:00Z",
                        "merge_sha": " merge ",
                    },
                    "newer": {
                        "updated_at": "2026-09-15T00:00:00Z",
                        "commit_sha": "new",
                    },
                    "invalid": None,
                }
            },
            2: {"receipts": {"only": {"commit_sha": " implementation "}}},
            3: {"receipts": []},
        },
    )
    assert custody._landing_shas(None, [1, 2, 3, 4]) == {
        1: "merge",
        2: "implementation",
    }
