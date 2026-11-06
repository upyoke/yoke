"""View selection preserves alarms while avoiding unused inventories."""

from datetime import timedelta
from unittest.mock import Mock

from runtime.api.domain import (
    steering_fleet_report_delivery_test_support as delivery_tests,
)
from runtime.api.domain.steering_fleet_report_delivery_test_support import (
    NOW,
    STEERING_SESSION,
)

from yoke_core.domain import steering_fleet_report_reads as reads
from yoke_core.domain.steering_fleet_report_compose import (
    compose_held_reports,
    combined_dict,
)
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_delivery import (
    claim_report_composition,
    steering_report_candidate,
    confirm_steering_report_delivery,
    record_report_delivery,
)
from yoke_core.domain.steering_fleet_report_watcher import watcher_dict
from yoke_core.domain.fleet_delta_disappearances import shown_rows, disappeared_lines

steering_scope = delivery_tests.steering_scope


def test_digest_has_same_bytes_and_alarm_identity_without_inventories(
    steering_scope, monkeypatch
):
    full = compose_held_reports(steering_scope, session_id=STEERING_SESSION, now=NOW)
    for name in (
        "launchable_surfaces",
        "live_session_counts",
        "live_launch_origin_counts",
        "load_native_models",
        "machine_capacities",
        "read_test_machines",
        "read_level_readout",
    ):
        monkeypatch.setattr(reads, name, Mock(side_effect=AssertionError(name)))
    light = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW, include_inventory=False
    )
    assert combined_hook_digest(light) == combined_hook_digest(full)
    assert light.fingerprint() == full.fingerprint()
    assert light.actionable == full.actionable
    assert light.sections[0].report.plan_limits == full.sections[0].report.plan_limits
    assert not light.sections[0].report.levels


def test_compact_watcher_preserves_displayed_rows_and_disappearance_reasons(
    steering_scope,
):
    combined = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    full = combined_dict(combined)
    compact = watcher_dict(combined)
    assert "body" not in compact
    assert "available" not in compact["scopes"][0]
    assert compact["digest"] == full["digest"]
    before = shown_rows(full, digest=True)
    after = shown_rows(compact, digest=True)
    assert before.keys() == after.keys()
    assert disappeared_lines(before, {}, full, None) == disappeared_lines(
        before, {}, compact, None
    )


def test_hook_and_watcher_reserve_one_composition_and_old_candidate_cannot_stamp(
    steering_scope,
):
    candidate = steering_report_candidate(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    assert candidate is not None
    assert (
        claim_report_composition(steering_scope, session_id=STEERING_SESSION, now=NOW)
        is None
    )
    assert (
        claim_report_composition(
            steering_scope, session_id=STEERING_SESSION, now=NOW + timedelta(minutes=30)
        )
        is not None
    )
    assert confirm_steering_report_delivery(steering_scope, candidate) is False
    assert (
        record_report_delivery(
            steering_scope,
            session_id=STEERING_SESSION,
            fingerprint=candidate.fingerprint,
            now=candidate.claimed_at,
        )
        is False
    )


def test_session_labels_preserve_commands_and_json_identity():
    from yoke_core.domain.steering_fleet_report_labels import label_text, label_rows

    labels = (("worker", "Ada on laptop"),)
    assert label_text("session worker `yoke say --session worker`", labels) == (
        "session Ada on laptop `yoke say --session worker`"
    )
    assert label_rows({"session_id": "worker"}, labels) == {
        "session_id": "worker",
        "session_label": "Ada on laptop",
    }


def test_machine_values_are_read_once_and_membership_filters_per_project(test_db):
    request = reads.FleetReportReads()
    factory = Mock(
        return_value=(
            ({1, 2}, Mock(machine_id="shared")),
            ({1}, Mock(machine_id="shared")),
        )
    )
    first = request.machine_facts(test_db, "limits", 1, factory)
    second = request.machine_facts(test_db, "limits", 2, factory)
    assert len(first) == 2
    assert len(second) == 1
    factory.assert_called_once()


def test_capacity_membership_rejects_malformed_lists_without_coercing_identity():
    from yoke_core.domain.steering_fleet_report_capacity import _projects

    assert _projects("broken") == frozenset()
    assert _projects("{}") == frozenset()
    assert _projects([1, "01", "unavailable"]) == frozenset({"1", "01"})
