"""Which published generation a local edit descends from.

A customized definition raises a question the digest alone cannot answer: is
this universe's edit sitting on top of the newest thing Yoke published, or on
something Yoke has since moved past? The first needs nothing. The second needs
a merge, because there are changes on both sides.

Answering it requires the baseline to have been *recorded* at publish time.
Inferring it later is guessing, and guessing at the relationship between a
universe's definitions and the canon is what this whole model replaced.
"""

from __future__ import annotations

from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import (
    list_current_workflows,
    publish_workflow_version,
)
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
)


def _workflow(conn, workflow_id: str = "issue") -> dict:
    return next(
        row for row in list_current_workflows(conn) if row["id"] == workflow_id
    )


def _edit(conn, workflow_id: str = "issue", label: str = "Filed") -> dict:
    definition = builtin_workflow_definition(workflow_id)["definition"]
    definition["stages"][0]["label"] = label
    return publish_workflow_version(
        conn, workflow_id=workflow_id, definition=definition,
    )


def _set_baseline(conn, version_id: int, baseline: int | None) -> None:
    """Rewrite a stored baseline, reaching past the immutability trigger.

    Published rows are immutable, so this is the only way to stand up the two
    situations a test cannot reach forwards: a row from before the baseline
    was recorded, and a universe whose baseline Yoke has since overtaken.
    """
    conn.execute(
        "ALTER TABLE workflow_versions DISABLE TRIGGER "
        f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
    )
    try:
        conn.execute(
            "UPDATE workflow_versions SET derived_from_canon_version = %s "
            "WHERE id = %s",
            (baseline, version_id),
        )
    finally:
        conn.execute(
            "ALTER TABLE workflow_versions ENABLE TRIGGER "
            f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
        )
    conn.commit()


def test_a_published_generation_records_no_baseline(test_db):
    """Yoke's own definitions are the baseline; they do not have one."""
    workflow = _workflow(test_db)
    stock = workflow["versions"][0]
    assert stock["provenance"]["kind"] == "canon"
    assert "derived_from_canon_version" not in stock["provenance"]


def test_an_edit_records_the_generation_it_started_from(test_db):
    newest = canon_generations("issue")[-1].canon_version
    _edit(test_db)

    workflow = _workflow(test_db)
    edited = workflow["versions"][-1]
    assert edited["provenance"] == {
        "kind": "local",
        "derived_from_canon_version": newest,
    }
    # Edited from the newest thing Yoke published, so nothing is behind.
    assert workflow["canon_status"]["state"] == "customized"
    assert workflow["canon_status"]["derived_from_canon_version"] == newest


def test_editing_an_edit_carries_the_original_baseline_forward(test_db):
    """The baseline is the last point Yoke and this universe agreed."""
    newest = canon_generations("issue")[-1].canon_version
    _edit(test_db, label="Filed")
    _edit(test_db, label="Filed again")

    versions = _workflow(test_db)["versions"]
    assert [version["provenance"]["kind"] for version in versions] == [
        "canon", "local", "local",
    ]
    assert all(
        version["provenance"]["derived_from_canon_version"] == newest
        for version in versions[1:]
    )


def test_an_overtaken_baseline_reports_that_an_update_would_merge(test_db):
    """The state that cannot be resolved by taking Yoke's copy."""
    newest = canon_generations("issue")[-1].canon_version
    published = _edit(test_db)
    # Stand in for Yoke publishing a generation after this universe forked.
    _set_baseline(test_db, int(published["version_id"]), newest - 1)

    status = _workflow(test_db)["canon_status"]
    assert status["state"] == "customized_update_available"
    assert status["derived_from_canon_version"] == newest - 1
    assert status["latest_canon_version"] == newest


def test_an_unrecorded_baseline_is_reported_as_unknown_not_guessed(test_db):
    """Rows published before the baseline existed claim nothing about it."""
    published = _edit(test_db)
    _set_baseline(test_db, int(published["version_id"]), None)

    workflow = _workflow(test_db)
    assert workflow["versions"][-1]["provenance"] == {
        "kind": "local",
        "derived_from_canon_version": None,
    }
    # Plain customization: asserting an update is available would claim a
    # relationship to the canon that was never recorded.
    assert workflow["canon_status"]["state"] == "customized"
    assert workflow["canon_status"]["derived_from_canon_version"] is None


def test_every_canon_status_state_is_reachable_and_distinct(test_db):
    """Stock, customized, and conflicted are distinguishable without guessing."""
    assert _workflow(test_db)["canon_status"]["state"] == "up_to_date"

    newest = canon_generations("issue")[-1].canon_version
    published = _edit(test_db)
    assert _workflow(test_db)["canon_status"]["state"] == "customized"

    _set_baseline(test_db, int(published["version_id"]), newest - 1)
    assert (
        _workflow(test_db)["canon_status"]["state"]
        == "customized_update_available"
    )
