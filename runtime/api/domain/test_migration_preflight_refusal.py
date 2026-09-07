"""What a release gate tells the operator when coverage is missing."""

from __future__ import annotations

from yoke_core.domain import migration_preflight_refusal as refusal


class TestRefusalMessage:
    def test_the_refusal_names_the_environment_and_the_entries(self):
        message = refusal.refusal_message("prod-db-admin", ["0002_b", "0003_c"])
        assert "prod" in message
        assert "0002_b" in message
        assert "0003_c" in message
        assert "per environment" in message

    def test_default_refusal_teaches_project_generic_rehearsal(self):
        message = refusal.refusal_message("prod", ["0002_b"])
        assert "yoke migration rehearse" in message
        assert "--help" in message
        assert "preflight_fleet_migrations" not in message
        assert "runtime.api.tools" not in message

    def test_injected_rehearse_command_appears_in_the_refusal(self):
        command = (
            "yoke watch preflight -- "
            "prod-db-admin --record-receipt --product-sha <sha> "
            "--receipt-env <control-plane-connection>"
        )
        message = refusal.refusal_message(
            "prod",
            ["0002_b"],
            rehearse_command=command,
        )
        assert "yoke watch preflight" in message
        assert "--record-receipt" in message
        assert "prod-db-admin" in message

    def test_one_entry_reads_as_one_rather_than_as_a_plural(self):
        message = refusal.refusal_message("stage", ["0002_b"])
        assert "1 migration history entry" in message

    def test_several_entries_read_as_plural(self):
        message = refusal.refusal_message("stage", ["0002_b", "0003_c"])
        assert "2 migration history entries" in message

    def test_the_build_is_named_when_known(self):
        message = refusal.refusal_message("stage", ["0002_b"], product_sha="abc123")
        assert "abc123" in message

    def test_no_empty_build_reference_is_printed_when_unknown(self):
        message = refusal.refusal_message("stage", ["0002_b"], product_sha="  ")
        assert "at  " not in message


class TestSchemaShapeRefusalMessage:
    def test_the_refusal_names_the_digest_and_the_environment(self):
        message = refusal.schema_shape_refusal_message("prod-db-admin", "shape1")
        assert "shape1" in message
        assert "prod" in message
        assert "per environment" in message


class TestReleaseRefusalMessage:
    def test_sibling_gaps_are_named_in_one_refusal(self):
        message = refusal.release_refusal_message(
            "prod",
            {"prod": ("0002_b",), "stage": ("0002_b",)},
            rehearse_commands={
                "prod": "yoke watch preflight -- prod-db-admin",
                "stage": "yoke watch preflight -- stage-db-admin",
            },
        )
        assert "prod" in message
        assert "stage" in message
        assert "per environment" in message
        assert "stage-db-admin" in message

    def test_a_covered_sibling_is_named_as_non_transferable(self):
        message = refusal.release_refusal_message(
            "stage",
            {"stage": ("0002_b",), "prod": ()},
        )
        assert "does not transfer" in message
        assert "prod" in message


class TestUnreadableMessage:
    def test_unreadable_is_stated_as_unknown_rather_than_as_unrehearsed(self):
        message = refusal.unreadable_message("stage", "connection refused")
        assert "unknown" in message
        assert "connection refused" in message

    def test_unreadable_says_it_is_refusing(self):
        assert "Refusing" in refusal.unreadable_message("stage", "timeout")

    def test_unreadable_names_the_environment_it_could_not_answer_for(self):
        assert "prod" in refusal.unreadable_message("prod-db-admin", "timeout")

    def test_unreadable_names_what_would_clear_it(self):
        message = refusal.unreadable_message("prod", "permission_denied")
        assert "project read" in message
        assert "re-run" in message
