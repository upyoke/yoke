"""Pure-inference + parser tests for yoke_core.domain.populate_registry.

Covers the owner/kind/type/severity inference helpers, the discovery output
parser, and metadata-table integrity. Full-pipeline tests (with a fake repo
fixture) live in test_populate_registry_pipeline.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import pytest


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------


def test_infer_owner_service_strips_sh_extension():
    from yoke_core.domain.populate_registry import infer_owner_service

    assert infer_owner_service("shepherd-dispatch.sh") == "shepherd-dispatch"
    assert infer_owner_service("packages/yoke-core/src/yoke_core/domain/events.py") == "events.py"


def test_infer_event_kind_pattern_matches():
    from yoke_core.domain.populate_registry import infer_event_kind

    # Most-specific patterns first (matches original shell case ordering).
    assert infer_event_kind("HarnessToolCallDenied") == "audit"
    assert infer_event_kind("HarnessToolCallCompleted") == "system"
    assert infer_event_kind("HarnessSessionStarted") == "system"
    assert infer_event_kind("AnomalyDetected") == "system"
    assert infer_event_kind("ShepherdDispatched") == "audit"
    assert infer_event_kind("ConductStepCompleted") == "system"
    assert infer_event_kind("DeploymentRunStarted") == "system"
    assert infer_event_kind("TestEventRecorded") == "system"
    assert infer_event_kind("HealthCheckPassed") == "system"
    assert infer_event_kind("PatternDetected") == "system"
    assert infer_event_kind("ItemStatusChanged") == "lifecycle"
    assert infer_event_kind("TaskStatusChanged") == "lifecycle"
    assert infer_event_kind("RandomBlobStatusChanged") == "lifecycle"
    assert infer_event_kind("UnrelatedEvent") == "system"


def test_infer_event_type_suffixes():
    from yoke_core.domain.populate_registry import infer_event_type

    cases: Iterable[Tuple[str, str]] = (
        ("SomethingStarted", "Started"),
        ("SomethingCompleted", "Completed"),
        ("SomethingFailed", "Failed"),
        ("SomethingPassed", "Passed"),
        ("SomethingChanged", "Changed"),
        ("SomethingDispatched", "Dispatched"),
        ("SomethingDetected", "Detected"),
        ("SomethingPromoted", "Promoted"),
        ("SomethingStopped", "Stopped"),
        ("SomethingEnded", "Ended"),
        ("SomethingCreated", "Created"),
        ("SomethingUpdated", "Updated"),
        ("SomethingDeleted", "Deleted"),
        ("UnclassifiedEvent", "Unknown"),
    )
    for event_name, expected in cases:
        assert infer_event_type(event_name) == expected, event_name


def test_infer_severity_escalates_failed_and_anomaly():
    from yoke_core.domain.populate_registry import infer_severity

    assert infer_severity("HarnessToolCallFailed") == "WARN"
    assert infer_severity("DeploymentFailed") == "WARN"
    assert infer_severity("AnomalyDetected") == "WARN"
    assert infer_severity("SomethingStarted") == "INFO"
    assert infer_severity("ItemStatusChanged") == "INFO"


# ---------------------------------------------------------------------------
# Discovery parsing + dedup
# ---------------------------------------------------------------------------


def test_parse_discovery_output_dedupes_by_name():
    from yoke_core.domain.populate_registry import _parse_discovery_output

    raw = "\n".join(
        [
            "HarnessToolCallCompleted|packages/yoke-core/src/yoke_core/domain/observe.py",
            "HarnessToolCallCompleted|packages/yoke-core/src/yoke_core/domain/tests/test_observe.py",
            "HarnessToolCallFailed|packages/yoke-core/src/yoke_core/domain/observe.py",
            "",
            "SessionDiscoveryProbe|runtime/harness/harness_session_start.py",
            "malformed-line-without-pipe",
        ]
    )
    parsed = _parse_discovery_output(raw)
    names = [name for name, _ in parsed]
    assert names == ["HarnessToolCallCompleted", "HarnessToolCallFailed", "SessionDiscoveryProbe"]
    # First occurrence wins — production path, not the test path.
    assert dict(parsed)["HarnessToolCallCompleted"].endswith("observe.py")
    assert "tests" not in dict(parsed)["HarnessToolCallCompleted"]


# ---------------------------------------------------------------------------
# Metadata-table integrity
# ---------------------------------------------------------------------------


def test_authoritative_metadata_contains_no_duplicates():
    """The authoritative metadata table must not have duplicate names —
    duplicates would cause inconsistent final state depending on order."""
    from yoke_core.domain.populate_registry import AUTHORITATIVE_METADATA

    names = [entry[0] for entry in AUTHORITATIVE_METADATA]
    assert len(names) == len(set(names)), "duplicate names in AUTHORITATIVE_METADATA"


def test_curated_events_contains_no_duplicates():
    from yoke_core.domain.populate_registry import CURATED_EVENTS

    names = [entry[0] for entry in CURATED_EVENTS]
    assert len(names) == len(set(names)), "duplicate names in CURATED_EVENTS"


# ---------------------------------------------------------------------------
# Hook-runner telemetry registry coverage
# ---------------------------------------------------------------------------


HOOK_RUNNER_TELEMETRY_EVENTS = (
    # (name, expected_event_type, expected_severity)
    ("HookDispatchTelemetry", "hook_dispatch", "INFO"),
    ("HookExecutionFailed", "hook_execution_failure", "WARN"),
    ("HookGuardrailEvaluated", "hook_guardrail_evaluated", "DEBUG"),
)


def test_hook_runner_telemetry_events_registered_in_authoritative_metadata():
    """Every runner-native hook telemetry name that hook_runner.telemetry can
    emit must appear in AUTHORITATIVE_METADATA with kind=system, the matching
    event_type, owner_service=runtime.harness.hook_runner, and the expected
    severity. Guards against rogue-event regressions surfaced by
    HC-event-registry-coverage."""
    from yoke_core.domain.populate_registry import AUTHORITATIVE_METADATA

    by_name = {entry[0]: entry for entry in AUTHORITATIVE_METADATA}

    for name, expected_type, expected_severity in HOOK_RUNNER_TELEMETRY_EVENTS:
        assert name in by_name, f"{name} missing from AUTHORITATIVE_METADATA"
        # AUTHORITATIVE_METADATA tuple order: (name, kind, event_type, service, severity, description)
        _, kind, event_type, service, severity, description = by_name[name]
        assert kind == "system", f"{name} kind={kind!r}, want 'system'"
        assert event_type == expected_type, (
            f"{name} event_type={event_type!r}, want {expected_type!r}"
        )
        assert service == "runtime.harness.hook_runner", (
            f"{name} owner_service={service!r}, want 'runtime.harness.hook_runner'"
        )
        assert severity == expected_severity, (
            f"{name} severity={severity!r}, want {expected_severity!r}"
        )
        assert description, f"{name} description is empty"


def test_authoritative_and_curated_tuple_order_distinct():
    """AUTHORITATIVE_METADATA and CURATED_EVENTS use different tuple orders for
    the (severity, description) tail. An author who copy-pastes a row between
    the two tables and forgets to swap the tail will silently flip severity and
    description -- this guard catches that class of edit. Applied to the new
    hook-runner telemetry rows so a paste into CURATED_EVENTS with swapped tail
    cannot land unnoticed."""
    from yoke_core.domain.populate_registry import (
        AUTHORITATIVE_METADATA,
        CURATED_EVENTS,
    )

    valid_severities = {"DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL"}

    # AUTHORITATIVE_METADATA tuple order is (name, kind, event_type, service, severity, description).
    # Severity sits at index 4 and is a controlled vocabulary; description at index 5 is free text.
    for entry in AUTHORITATIVE_METADATA:
        assert len(entry) == 6, f"AUTHORITATIVE_METADATA entry not 6-tuple: {entry!r}"
        name, _kind, _type, _service, severity, description = entry
        assert severity in valid_severities, (
            f"AUTHORITATIVE_METADATA[{name}] severity={severity!r} is not a known "
            f"severity -- check for swapped severity/description ordering"
        )
        # Free-text description must not look like a severity token.
        assert description not in valid_severities, (
            f"AUTHORITATIVE_METADATA[{name}] description={description!r} looks like "
            f"a severity token -- check for swapped severity/description ordering"
        )

    # CURATED_EVENTS tuple order is (name, kind, event_type, service, description, severity).
    # Severity sits at index 5 here, NOT index 4. Same controlled vocabulary applies.
    for entry in CURATED_EVENTS:
        assert len(entry) == 6, f"CURATED_EVENTS entry not 6-tuple: {entry!r}"
        name, _kind, _type, _service, description, severity = entry
        assert severity in valid_severities, (
            f"CURATED_EVENTS[{name}] severity={severity!r} is not a known severity "
            f"-- check for swapped severity/description ordering"
        )
        assert description not in valid_severities, (
            f"CURATED_EVENTS[{name}] description={description!r} looks like a "
            f"severity token -- check for swapped severity/description ordering"
        )


# ---------------------------------------------------------------------------
# Residual non-hook rogue-event registry coverage
# ---------------------------------------------------------------------------


REGISTRY_RECONCILED_ACTIVE = (
    # (name, expected_event_kind, expected_event_type, expected_owner_service, expected_severity)
    ("QARunCaptured", "lifecycle", "qa_execution", "yoke_core.domain.qa_execution", "INFO"),
)


REGISTRY_RECONCILED_RETIRED = (
    "ClaimReacquiredAfterHandoff",
    "PathContextMigrated",
    "LeakAttempt",
    "BodyRegenerated",
    "BodyRegenerationFailed",
)


REGISTRY_RECONCILED_DEPRECATED = (
    "BaselinePromoted",
    "BaselineRecorded",
    "ChargeDecisionMade",
    "FeedCompleted",
    "FeedStarted",
    "QAArtifactAttached",
)


def test_qa_run_captured_registered_in_authoritative_metadata():
    """QARunCaptured must be registered active with the same kind/type as
    QARunCompleted so the event-registry rogue check stops flagging the live
    qa_execution emitter."""
    from yoke_core.domain.populate_registry import AUTHORITATIVE_METADATA

    by_name = {entry[0]: entry for entry in AUTHORITATIVE_METADATA}
    for name, kind, event_type, service, severity in REGISTRY_RECONCILED_ACTIVE:
        assert name in by_name, f"{name} missing from AUTHORITATIVE_METADATA"
        _, got_kind, got_type, got_service, got_severity, description = by_name[name]
        assert got_kind == kind, f"{name} kind={got_kind!r}, want {kind!r}"
        assert got_type == event_type, f"{name} event_type={got_type!r}, want {event_type!r}"
        assert got_service == service, f"{name} owner_service={got_service!r}, want {service!r}"
        assert got_severity == severity, f"{name} severity={got_severity!r}, want {severity!r}"
        assert description, f"{name} description is empty"


def test_registry_reconciled_retired_names_in_retire_list():
    """Each rogue/stale-active name that was renamed or had its emitter removed
    must appear in RETIRE_LIST so the populator flips status to retired."""
    from yoke_core.domain.populate_registry import RETIRE_LIST

    retire_set = set(RETIRE_LIST)
    for name in REGISTRY_RECONCILED_RETIRED:
        assert name in retire_set, f"{name} missing from RETIRE_LIST"


def test_registry_reconciled_deprecated_names_in_deprecate_list():
    """Each stale-active name with no live emitter and no successor must appear
    in DEPRECATE_LIST so the populator flips status to deprecated."""
    from yoke_core.domain.populate_registry import DEPRECATE_LIST

    deprecate_set = set(DEPRECATE_LIST)
    for name in REGISTRY_RECONCILED_DEPRECATED:
        assert name in deprecate_set, f"{name} missing from DEPRECATE_LIST"


def test_expected_low_cadence_active_names_stay_authoritative_and_active():
    """Low-cadence events are still live; the doctor HC ignores only their stale
    emission cadence, not their registry row quality."""
    from yoke_core.domain.populate_registry import (
        AUTHORITATIVE_METADATA,
        DEPRECATE_LIST,
        RETIRE_LIST,
    )
    from yoke_core.domain.populate_registry_data_authoritative import EXPECTED_LOW_CADENCE_ACTIVE

    by_name = {entry[0]: entry for entry in AUTHORITATIVE_METADATA}
    missing = set(EXPECTED_LOW_CADENCE_ACTIVE) - set(by_name)
    assert not missing, f"expected low-cadence names missing metadata: {sorted(missing)}"

    inactive = set(EXPECTED_LOW_CADENCE_ACTIVE) & (set(DEPRECATE_LIST) | set(RETIRE_LIST))
    assert not inactive, f"expected low-cadence names marked inactive: {sorted(inactive)}"


def test_retired_rogue_rows_have_authoritative_metadata_rows():
    """Retiring a name through RETIRE_LIST only flips status to retired when the
    row already exists. The 3 spec-named retirements (ClaimReacquiredAfterHandoff,
    PathContextMigrated, LeakAttempt) had their registry rows previously deleted,
    so AUTHORITATIVE_METADATA must carry replacement rows that
    _ensure_authoritative_metadata can insert before the retire layer runs."""
    from yoke_core.domain.populate_registry import AUTHORITATIVE_METADATA

    by_name = {entry[0] for entry in AUTHORITATIVE_METADATA}
    for name in ("ClaimReacquiredAfterHandoff", "PathContextMigrated", "LeakAttempt"):
        assert name in by_name, (
            f"{name} retired via RETIRE_LIST but has no AUTHORITATIVE_METADATA row; "
            f"_retire_events skips silently when the row does not yet exist."
        )


def test_no_disposition_conflicts_between_retire_and_deprecate():
    """A name must not appear in BOTH RETIRE_LIST and DEPRECATE_LIST.
    The populator applies deprecate before retire — a name in both lists would
    end up retired even when the author intended deprecated, or vice versa."""
    from yoke_core.domain.populate_registry import DEPRECATE_LIST, RETIRE_LIST

    overlap = set(DEPRECATE_LIST) & set(RETIRE_LIST)
    assert not overlap, f"names appear in both DEPRECATE_LIST and RETIRE_LIST: {sorted(overlap)}"
