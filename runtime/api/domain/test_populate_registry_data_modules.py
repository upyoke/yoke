"""Regression coverage for modular event-registry population data."""

from pathlib import Path

from yoke_core.domain import populate_registry_data_authoritative as authoritative
from yoke_core.domain import populate_registry_data_curated as curated
from yoke_core.domain import populate_registry_data_lifecycle as lifecycle
from yoke_core.domain import populate_registry_data_updates as updates


MAX_DATA_MODULE_LINES = 325
DATA_MODULES = (authoritative, curated, lifecycle, updates)


def test_registry_data_modules_retain_authored_row_headroom() -> None:
    for module in DATA_MODULES:
        module_path = Path(module.__file__)
        line_count = len(module_path.read_text().splitlines())
        assert line_count <= MAX_DATA_MODULE_LINES, (
            f"{module_path.name} has {line_count} lines; "
            f"keep it at or below {MAX_DATA_MODULE_LINES}"
        )


def test_authoritative_rows_are_guarded_from_formatter_expansion() -> None:
    source = Path(authoritative.__file__).read_text()
    guard_offset = source.index("# fmt: off")
    metadata_offset = source.index("\nAUTHORITATIVE_METADATA:", guard_offset)
    assert guard_offset < metadata_offset


def test_split_modules_preserve_public_tuple_contracts() -> None:
    assert authoritative.DEPRECATE_LIST is lifecycle.DEPRECATE_LIST
    assert authoritative.PURGED_EVENT_NAMES is lifecycle.PURGED_EVENT_NAMES
    assert (
        authoritative.EXPECTED_LOW_CADENCE_ACTIVE
        is lifecycle.EXPECTED_LOW_CADENCE_ACTIVE
    )
    assert curated.CORRECTIVE_UPDATES is updates.CORRECTIVE_UPDATES
    assert curated.SEVERITY_ONLY_UPDATES is updates.SEVERITY_ONLY_UPDATES


def test_active_discovered_events_have_authoritative_metadata() -> None:
    expected = {
        "DriftReviewCompleted": (
            "lifecycle",
            "drift_review",
            "yoke_core.domain.sessions_analytics_dispatch",
            "STATUS",
        ),
        "HarnessSessionResumed": (
            "system",
            "session_lifecycle",
            "yoke_core.domain.sessions_lifecycle_resumption_emit",
            "INFO",
        ),
        "OuroborosFieldNoteAppended": (
            "domain",
            "ouroboros_feedback",
            "yoke_core.domain.handlers.ouroboros_field_note",
            "INFO",
        ),
        "PathClaimCoverageSuppressed": (
            "hook",
            "lint_decision",
            "yoke_core.domain.check_path_claim_coverage_at_commit",
            "WARN",
        ),
        "RenderRelationshipRecorded": (
            "lifecycle",
            "path_context",
            "yoke_core.domain.agents_render_path_context",
            "INFO",
        ),
        "SectionAppended": (
            "system",
            "data_mutation",
            "yoke_core.domain.item_field_transform_sections",
            "INFO",
        ),
        "SessionAnchorContentionObserved": (
            "lifecycle",
            "session_lifecycle",
            "yoke_core.domain.session_process_anchors",
            "WARN",
        ),
        "SourceDevRunMainCheckoutFallback": (
            "audit",
            "source_dev_run",
            "yoke_core.tools.source_dev_run",
            "WARN",
        ),
        "StandaloneMergeReceiptRecorded": (
            "lifecycle",
            "merge_lifecycle",
            "yoke_core.domain.standalone_item_merge_receipt",
            "INFO",
        ),
    }
    by_name = {row[0]: row[1:] for row in authoritative.AUTHORITATIVE_METADATA}

    for name, metadata in expected.items():
        assert by_name[name][:4] == metadata
        assert not by_name[name][4].startswith("Auto-discovered from ")
