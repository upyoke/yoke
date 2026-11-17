"""A member released mid-run is not stamped deploy_stage ``complete``.

The driver reads its members at start. A member released during the run (its
candidate is outside the frozen lineage) awaits a later release, so the final
stamp, and the delivery stamps after it, use the members the run still holds.
"""

from __future__ import annotations

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deploy_pipeline_reporting as reporting

RUN = "run-20261117-002"


def _stamps(monkeypatch) -> list[tuple[str, list[str]]]:
    stamped: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        reporting,
        "_set_deploy_stage",
        lambda stage, _run, items, sd=None: stamped.append((stage, list(items))),
    )
    return stamped


def test_released_member_is_not_stamped_complete(monkeypatch):
    stamped = _stamps(monkeypatch)
    monkeypatch.setattr(control_plane, "current_member_refs", lambda _run: ["YOK-1"])
    members = ["YOK-1", "YOK-5281"]

    refusal = reporting.stamp_held_members_complete(RUN, members)

    assert refusal == ""
    assert stamped == [("complete", ["YOK-1"])]
    # Narrowed in place so the delivery stamps that follow skip it too.
    assert members == ["YOK-1"]


def test_unreadable_membership_stamps_nothing_and_names_recovery(monkeypatch):
    stamped = _stamps(monkeypatch)

    def _refused(_run):
        raise control_plane.DeploymentControlPlaneError("deployment_runs.get failed: down")

    monkeypatch.setattr(control_plane, "current_member_refs", _refused)

    refusal = reporting.stamp_held_members_complete(RUN, ["YOK-1"])

    assert stamped == []
    assert "no member was stamped complete" in refusal
    assert f"yoke watch deploy -- {RUN}" in refusal


def test_item_less_run_stamps_complete_without_a_membership_read(monkeypatch):
    stamped = _stamps(monkeypatch)

    def _unexpected(_run):
        raise AssertionError("an item-less run has no members to re-read")

    monkeypatch.setattr(control_plane, "current_member_refs", _unexpected)

    assert reporting.stamp_held_members_complete(RUN, []) == ""
    assert stamped == [("complete", [])]


def test_current_member_refs_reads_the_held_members(monkeypatch):
    calls = []

    def _call(function_id, run_id, payload):
        calls.append((function_id, run_id, payload))
        return {"value": [{"ref": "YOK-1", "id": 1}]}

    monkeypatch.setattr(control_plane, "_call", _call)

    assert control_plane.current_member_refs(RUN) == ["YOK-1"]
    assert calls == [("deployment_runs.get", RUN, {"field": "member_items"})]
