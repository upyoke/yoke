"""One unadapted workflow must not hide healthy frontier items."""

from copy import deepcopy
from dataclasses import replace

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.frontier_classify import classify_next_action
from yoke_core.domain.frontier_list_read import list_frontier
from yoke_core.domain.frontier_workflow_versions import FrontierWorkflowVersions
from yoke_core.domain.handlers.frontier_list import FrontierListResponse


@pytest.mark.parametrize(
    "invalid,reason",
    [("skill", "Workflow skill 'advance' has no frontier adapter"),
     ("stage", "Unknown stage 'idea'")],
)
def test_frontier_reports_bad_item_and_lists_healthy_item(
    test_db, monkeypatch, invalid, reason,
):
    for item_id in (1, 2):
        insert_item(test_db, id=item_id, workflow_id="dash", status="idea",
                    spec="A complete fixture spec for frontier scheduling.")
    test_db.commit()
    original = FrontierWorkflowVersions.runtime_for
    invalid_runtimes = []

    def runtime_for(self, conn, item):
        runtime = original(self, conn, item)
        if int(item["id"]) != 1:
            return runtime
        # Model a legacy pin at the loader boundary; do not weaken today's
        # workflow publication validation to persist an unsupported skill.
        definition = deepcopy(runtime.definition)
        if invalid == "skill":
            definition["skill_bindings"][0]["skill_id"] = "advance"
        else:
            definition["stages"] = [
                stage for stage in definition["stages"] if stage["id"] != "idea"
            ]
        runtime = replace(runtime, definition=definition)
        invalid_runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(FrontierWorkflowVersions, "runtime_for", runtime_for)

    result = list_frontier(project="yoke")

    assert {row["item_id"] for row in result["ready_rows"]} == {"YOK-2"}
    assert result["blocked_rows"] == []
    assert len(result["diagnostics"]) == 1
    diagnostic = result["diagnostics"][0]
    assert diagnostic["item_id"] == "YOK-1"
    assert reason in diagnostic["reason"]
    assert "Repair" in diagnostic["recovery"]
    assert FrontierListResponse.model_validate(result).diagnostics == [diagnostic]
    # Callers outside the frontier still see the misconfiguration.
    with pytest.raises(ValueError, match=reason):
        classify_next_action(invalid_runtimes[0], "idea")


def test_healthy_frontier_has_no_diagnostics(test_db):
    insert_item(test_db, id=1, workflow_id="dash", status="idea",
                spec="A complete fixture spec for frontier scheduling.")
    test_db.commit()

    assert list_frontier(project="yoke")["diagnostics"] == []
