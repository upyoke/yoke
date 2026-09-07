"""The receipt contract a release gate reads before allocating a tag."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_core.domain import migration_preflight_receipt as receipt


def _covered(entries=(), *, digest: str = "", run: str = "20260101T000000Z") -> dict:
    """The coverage leaves one passing rehearsal leaves on its environment."""
    values = {receipt.entry_coverage_path(name): run for name in entries}
    if digest:
        values[receipt.schema_shape_coverage_path(digest)] = run
    return values


class TestEnvironmentNaming:
    def test_an_admin_connection_names_the_environment_it_rehearses(self):
        assert receipt.target_environment_for_admin_env("prod-db-admin") == "prod"
        assert receipt.target_environment_for_admin_env("stage-db-admin") == "stage"

    def test_an_environment_name_is_already_itself(self):
        assert receipt.target_environment_for_admin_env("prod") == "prod"
        assert receipt.target_environment_for_admin_env("stage") == "stage"

    def test_surrounding_whitespace_does_not_make_a_new_environment(self):
        assert receipt.target_environment_for_admin_env("  stage  ") == "stage"

    def test_an_unknown_environment_passes_through_rather_than_guessing(self):
        assert receipt.target_environment_for_admin_env("sandbox") == "sandbox"


class TestCoveragePaths:
    def test_a_history_entry_addresses_one_leaf_under_the_entry_namespace(self):
        assert (
            receipt.entry_coverage_path("0001_a")
            == f"{receipt.ENTRY_PREFIX}.0001_a"
        )

    def test_a_digest_addresses_one_leaf_under_the_schema_shape_namespace(self):
        assert (
            receipt.schema_shape_coverage_path("abc")
            == f"{receipt.SCHEMA_SHAPE_PREFIX}.abc"
        )

    def test_a_dotted_name_is_refused_rather_than_split_into_nested_keys(self):
        # Settings paths split on ".", so accepting one here would write
        # coverage at a key no reader asks for and read coverage nothing wrote.
        with pytest.raises(receipt.ReceiptPathError) as raised:
            receipt.entry_coverage_path("0001.a")
        assert "cannot contain '.'" in str(raised.value)

    def test_an_empty_name_is_refused(self):
        with pytest.raises(receipt.ReceiptPathError):
            receipt.schema_shape_coverage_path("   ")

    def test_one_read_asks_for_every_entry_and_the_digest(self):
        paths = receipt.coverage_paths(["0001_a", "0002_b"], "abc")
        assert paths == (
            receipt.entry_coverage_path("0001_a"),
            receipt.entry_coverage_path("0002_b"),
            receipt.schema_shape_coverage_path("abc"),
        )

    def test_a_missing_digest_leaves_the_entry_paths_alone(self):
        assert receipt.coverage_paths(["0001_a"], "") == (
            receipt.entry_coverage_path("0001_a"),
        )

    def test_repeated_entries_are_asked_for_once(self):
        assert receipt.coverage_paths(["0001_a", "0001_a"], "") == (
            receipt.entry_coverage_path("0001_a"),
        )


class TestReceiptAssignments:
    def test_every_covered_entry_points_at_the_run_that_covered_it(self):
        run, assignments = receipt.receipt_assignments(
            "abc123",
            ["0002_b", "0001_a"],
            moment=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
        assert run == "20260102T030405Z"
        assert assignments[receipt.entry_coverage_path("0001_a")] == run
        assert assignments[receipt.entry_coverage_path("0002_b")] == run

    def test_blank_entries_are_dropped_rather_than_recorded_as_coverage(self):
        _run, assignments = receipt.receipt_assignments("abc", ["0001_a", "", "  "])
        entry_paths = [
            path for path in assignments if path.startswith(receipt.ENTRY_PREFIX)
        ]
        assert entry_paths == [receipt.entry_coverage_path("0001_a")]

    def test_the_run_carries_the_build_and_engine_that_rehearsed_it(self):
        run, assignments = receipt.receipt_assignments(
            " abc123 ",
            ["0001_a"],
            engine_artifact={"kind": "wheel", "name": "yoke.whl", "sha256": "d1"},
            schema_shape_digest="shape1",
            database_count=4,
        )
        assert assignments[f"{receipt.RUN_PREFIX}.{run}.product_sha"] == "abc123"
        assert "yoke.whl" in assignments[f"{receipt.RUN_PREFIX}.{run}.engine"]
        assert assignments[f"{receipt.RUN_PREFIX}.{run}.schema_shape"] == "shape1"
        assert assignments[f"{receipt.RUN_PREFIX}.{run}.databases"] == 4
        assert assignments[f"{receipt.RUN_PREFIX}.{run}.rehearsed_at"]

    def test_an_uncounted_fleet_records_no_database_count_rather_than_zero(self):
        run, assignments = receipt.receipt_assignments("abc", ["0001_a"])
        assert f"{receipt.RUN_PREFIX}.{run}.databases" not in assignments

    def test_the_digest_leaf_points_at_the_same_run(self):
        run, assignments = receipt.receipt_assignments(
            "abc", ["0001_a"], schema_shape_digest="shape1"
        )
        assert assignments[receipt.schema_shape_coverage_path("shape1")] == run

    def test_a_dotted_entry_refuses_the_whole_receipt(self):
        with pytest.raises(receipt.ReceiptPathError):
            receipt.receipt_assignments("abc", ["0001.a"])


class TestCoverage:
    def test_coverage_is_the_union_across_rehearsals_not_the_newest_one(self):
        values = {
            **_covered(["0001_a"], run="20260101T000000Z"),
            **_covered(["0002_b"], run="20260202T000000Z"),
        }
        assert receipt.covered_entries(values, ["0001_a", "0002_b"]) == frozenset(
            {"0001_a", "0002_b"}
        )

    def test_a_stage_receipt_is_not_production_evidence(self):
        # Coverage read for prod can only come from prod's own settings row,
        # so a stage rehearsal is structurally invisible here.
        assert receipt.covered_entries({}, ["0001_a"]) == frozenset()

    def test_an_absent_leaf_is_uncovered_rather_than_covered(self):
        values = {receipt.entry_coverage_path("0001_a"): None}
        assert receipt.covered_entries(values, ["0001_a"]) == frozenset()

    def test_a_blank_leaf_is_uncovered_rather_than_quietly_passing(self):
        values = {receipt.entry_coverage_path("0001_a"): "  "}
        assert receipt.covered_entries(values, ["0001_a"]) == frozenset()

    def test_a_non_string_leaf_is_not_read_as_a_rehearsal_identity(self):
        values = {receipt.entry_coverage_path("0001_a"): True}
        assert receipt.covered_entries(values, ["0001_a"]) == frozenset()

    def test_a_dotted_history_name_is_skipped_rather_than_crashing_the_gate(self):
        # Such a name cannot be written either, so it can only ever be
        # uncovered — and one malformed name must not make the rest
        # unanswerable.
        values = _covered(["0001_a"])
        assert receipt.covered_entries(values, ["0001_a", "0002.b"]) == frozenset(
            {"0001_a"}
        )


class TestUncovered:
    def test_nothing_is_uncovered_when_every_entry_has_a_receipt(self):
        values = _covered(["0001_a", "0002_b"])
        assert receipt.uncovered(["0001_a", "0002_b"], values) == ()

    def test_an_entry_no_receipt_covers_is_reported(self):
        assert receipt.uncovered(["0001_a", "0002_b"], _covered(["0001_a"])) == (
            "0002_b",
        )

    def test_history_order_is_preserved_so_the_message_reads_in_apply_order(self):
        assert receipt.uncovered(["0003_c", "0001_a"], {}) == ("0003_c", "0001_a")

    def test_with_no_receipts_at_all_the_whole_history_is_uncovered(self):
        # This is the bootstrap state, and refusing is correct: one passing
        # preflight with --record-receipt both clears it and proves the fleet.
        assert receipt.uncovered(["0001_a"], {}) == ("0001_a",)

    def test_a_receipt_covering_more_than_this_build_carries_is_harmless(self):
        values = _covered(["0001_a", "0002_b", "0003_c"])
        assert receipt.uncovered(["0001_a"], values) == ()


class TestUncoveredSchemaShape:
    def test_a_covered_digest_reports_nothing_missing(self):
        assert receipt.uncovered_schema_shape("shape1", _covered(digest="shape1")) == ()

    def test_a_different_digest_is_not_coverage_for_this_build(self):
        assert receipt.uncovered_schema_shape("shape2", _covered(digest="shape1")) == (
            "shape2",
        )

    def test_an_unknown_digest_is_reported_as_the_gap_itself(self):
        assert receipt.uncovered_schema_shape("", {}) == ("",)


class TestCoverageByEnvironment:
    def test_each_environment_is_answered_from_its_own_document(self):
        coverage = receipt.coverage_by_environment(
            ["0001_a", "0002_b"],
            {"stage": _covered(["0001_a", "0002_b"]), "prod": _covered(["0001_a"])},
        )
        assert coverage == {"stage": (), "prod": ("0002_b",)}

    def test_an_environment_with_no_document_is_wholly_uncovered(self):
        coverage = receipt.coverage_by_environment(["0001_a"], {})
        assert coverage == {"stage": ("0001_a",), "prod": ("0001_a",)}

    def test_an_admin_connection_name_answers_under_its_environment(self):
        coverage = receipt.coverage_by_environment(
            ["0001_a"], {"prod": _covered(["0001_a"])}, ["prod-db-admin"]
        )
        assert coverage == {"prod": ()}


class TestAdminConnectionForEnvironment:
    def test_an_admin_connection_is_already_itself(self):
        assert (
            receipt.admin_connection_for_environment("prod-db-admin") == "prod-db-admin"
        )

    def test_prod_resolves_to_the_admin_connection(self):
        assert receipt.admin_connection_for_environment("prod") == "prod-db-admin"

    def test_stage_resolves_to_the_admin_connection(self):
        assert receipt.admin_connection_for_environment("stage") == "stage-db-admin"


class TestRehearsedBuildDescription:
    def test_a_source_tree_receipt_is_labeled_as_source_tree(self):
        assert "source-tree engine" in receipt.rehearsed_build_description(
            {"kind": "ambient", "name": "import-path", "schema_origin": "/src"}
        )

    def test_a_wheel_receipt_names_the_wheel_and_digest(self):
        labeled = receipt.rehearsed_build_description(
            {"kind": "wheel", "name": "yoke_core.whl", "sha256": "abc"}
        )
        assert "release wheel yoke_core.whl" in labeled
        assert "sha256:abc" in labeled

    def test_an_unnamed_artifact_is_labeled_unspecified(self):
        assert "unspecified engine" == receipt.rehearsed_build_description(None)
