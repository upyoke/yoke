"""The receipt contract a release gate reads before allocating a tag."""

from __future__ import annotations

import json

from yoke_core.domain import migration_preflight_receipt as receipt


def _row(environment: str, entries, *, product_sha: str = "abc123") -> dict:
    """One queried event row carrying a receipt, envelope-encoded as queried."""
    envelope = {
        "event_name": receipt.EVENT_NAME,
        "context": {
            receipt.ENVIRONMENT_KEY: environment,
            receipt.PRODUCT_SHA_KEY: product_sha,
            receipt.ENTRIES_KEY: entries,
        },
    }
    return {"envelope": json.dumps(envelope)}


class TestEmitEnvelopeIsAccepted:
    def test_the_source_type_is_one_the_emit_surface_accepts(self):
        # A rejected emit is a passing rehearsal the gate cannot see, and the
        # rejection happens at the emit surface rather than here — so the only
        # place this can be caught early is against that surface's own enum.
        from yoke_core.domain import events_crud

        assert receipt.SOURCE_TYPE in events_crud.VALID_SOURCE_TYPES

    def test_the_severity_free_envelope_fields_are_non_empty(self):
        assert receipt.EVENT_NAME
        assert receipt.EVENT_KIND
        assert receipt.EVENT_TYPE


class TestEnvironmentNaming:
    def test_an_admin_connection_names_the_environment_it_rehearses(self):
        assert receipt.target_environment_for_admin_env("prod-db-admin") == "production"
        assert receipt.target_environment_for_admin_env("stage-db-admin") == "stage"

    def test_a_release_environment_is_already_itself(self):
        assert receipt.target_environment_for_admin_env("production") == "production"
        assert receipt.target_environment_for_admin_env("stage") == "stage"

    def test_the_production_alias_resolves_without_the_admin_suffix(self):
        assert receipt.target_environment_for_admin_env("prod") == "production"

    def test_surrounding_whitespace_does_not_make_a_new_environment(self):
        assert receipt.target_environment_for_admin_env("  stage  ") == "stage"

    def test_an_unknown_environment_passes_through_rather_than_guessing(self):
        assert receipt.target_environment_for_admin_env("sandbox") == "sandbox"


class TestReceiptContext:
    def test_the_recorded_environment_is_the_release_facing_name(self):
        context = receipt.receipt_context("prod-db-admin", "abc", ["0001_a"])
        assert context[receipt.ENVIRONMENT_KEY] == "production"

    def test_entries_are_sorted_and_deduplicated(self):
        context = receipt.receipt_context("stage", "abc", ["0002_b", "0001_a", "0002_b"])
        assert context[receipt.ENTRIES_KEY] == ["0001_a", "0002_b"]

    def test_blank_entries_are_dropped_rather_than_recorded_as_coverage(self):
        context = receipt.receipt_context("stage", "abc", ["0001_a", "", "   "])
        assert context[receipt.ENTRIES_KEY] == ["0001_a"]

    def test_the_product_sha_is_recorded_for_audit(self):
        context = receipt.receipt_context("stage", " abc123 ", ["0001_a"])
        assert context[receipt.PRODUCT_SHA_KEY] == "abc123"


class TestCoverage:
    def test_coverage_is_the_union_across_receipts_not_the_newest_one(self):
        rows = [_row("stage", ["0001_a"]), _row("stage", ["0002_b"])]
        assert receipt.covered_entries(rows, "stage") == frozenset({"0001_a", "0002_b"})

    def test_a_stage_receipt_is_not_production_evidence(self):
        rows = [_row("stage", ["0001_a", "0002_b"])]
        assert receipt.covered_entries(rows, "production") == frozenset()

    def test_a_receipt_is_found_when_the_gate_asks_by_admin_connection_name(self):
        rows = [_row("production", ["0001_a"])]
        assert receipt.covered_entries(rows, "prod-db-admin") == frozenset({"0001_a"})

    def test_an_already_parsed_envelope_reads_the_same_as_an_encoded_one(self):
        encoded = _row("stage", ["0001_a"])
        parsed = {"envelope": json.loads(encoded["envelope"])}
        assert receipt.covered_entries([parsed], "stage") == frozenset({"0001_a"})

    def test_a_malformed_row_does_not_poison_an_answerable_question(self):
        rows = [
            {"envelope": "{not json"},
            {},
            {"envelope": 17},
            {"envelope": json.dumps({"context": "not a mapping"})},
            _row("stage", ["0001_a"]),
        ]
        assert receipt.covered_entries(rows, "stage") == frozenset({"0001_a"})

    def test_a_string_entry_list_contributes_nothing_rather_than_characters(self):
        # A receipt whose entries field is a bare string is malformed. Iterating
        # it would manufacture single-character "coverage" that matches nothing
        # and hides the malformation.
        assert receipt.covered_entries([_row("stage", "0001_a")], "stage") == frozenset()


class TestUncovered:
    def test_nothing_is_uncovered_when_every_entry_has_a_receipt(self):
        rows = [_row("stage", ["0001_a", "0002_b"])]
        assert receipt.uncovered(["0001_a", "0002_b"], rows, "stage") == ()

    def test_an_entry_no_receipt_covers_is_reported(self):
        rows = [_row("stage", ["0001_a"])]
        assert receipt.uncovered(["0001_a", "0002_b"], rows, "stage") == ("0002_b",)

    def test_history_order_is_preserved_so_the_message_reads_in_apply_order(self):
        assert receipt.uncovered(["0003_c", "0001_a"], [], "stage") == (
            "0003_c",
            "0001_a",
        )

    def test_with_no_receipts_at_all_the_whole_history_is_uncovered(self):
        # This is the bootstrap state, and refusing is correct: one passing
        # preflight with --record-receipt both clears it and proves the fleet.
        assert receipt.uncovered(["0001_a"], [], "production") == ("0001_a",)

    def test_a_receipt_covering_more_than_this_build_carries_is_harmless(self):
        rows = [_row("stage", ["0001_a", "0002_b", "0003_c"])]
        assert receipt.uncovered(["0001_a"], rows, "stage") == ()


class TestRefusalMessage:
    def test_the_refusal_names_the_environment_and_the_entries(self):
        message = receipt.refusal_message("prod-db-admin", ["0002_b", "0003_c"])
        assert "production" in message
        assert "0002_b" in message
        assert "0003_c" in message

    def test_the_refusal_prints_the_command_that_resolves_it(self):
        message = receipt.refusal_message("production", ["0002_b"])
        assert "preflight_fleet_migrations" in message
        assert "--record-receipt" in message

    def test_the_command_names_the_admin_connection_not_the_release_name(self):
        # The operator runs the preflight against a cluster, and "production"
        # is not a configured connection.
        message = receipt.refusal_message("production", ["0002_b"])
        assert "prod-db-admin" in message

    def test_a_stage_refusal_names_the_stage_connection(self):
        assert "stage-db-admin" in receipt.refusal_message("stage", ["0002_b"])

    def test_one_entry_reads_as_one_rather_than_as_a_plural(self):
        message = receipt.refusal_message("stage", ["0002_b"])
        assert "1 migration history entry" in message

    def test_several_entries_read_as_plural(self):
        message = receipt.refusal_message("stage", ["0002_b", "0003_c"])
        assert "2 migration history entries" in message

    def test_the_build_is_named_when_known(self):
        message = receipt.refusal_message("stage", ["0002_b"], product_sha="abc123")
        assert "abc123" in message

    def test_no_empty_build_reference_is_printed_when_unknown(self):
        message = receipt.refusal_message("stage", ["0002_b"], product_sha="  ")
        assert "at  " not in message


class TestUnreadableMessage:
    def test_unreadable_is_stated_as_unknown_rather_than_as_unrehearsed(self):
        message = receipt.unreadable_message("stage", "connection refused")
        assert "unknown" in message
        assert "connection refused" in message

    def test_unreadable_says_it_is_refusing(self):
        assert "Refusing" in receipt.unreadable_message("stage", "timeout")

    def test_unreadable_names_the_environment_it_could_not_answer_for(self):
        assert "production" in receipt.unreadable_message("prod-db-admin", "timeout")
