"""Tests for the ``projects.capabilities.list`` read handler and its read.

Real-DB coverage on the ``test_db`` fixture: kind/state derivation for
NULL vs stamped ``verified_at``, the GitHub freshness overlay from the
App installation / repo binding stamps, the project filter, the curated
non-secret settings summary, the structural secrets exclusion (no
``capability_secrets`` value ever reaches the payload), registration,
and UI allowlist membership.
"""

from __future__ import annotations

from runtime.api.domain.handlers.capabilities_list_test_support import (
    insert_capability as _insert_capability,
    insert_github_binding as _insert_github_binding,
    iso_timestamp as _iso,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.capabilities_list_read import list_capabilities


class TestKindAndStateDerivation:
    def test_migration_model_is_a_declared_model(self, test_db):
        _insert_capability(test_db, "migration_model")
        rows = list_capabilities()
        assert [row["type"] for row in rows] == ["migration_model"]
        assert rows[0]["kind"] == "declared_model"
        assert rows[0]["state"] == "ready"

    def test_null_verified_at_reads_configured_unverified(self, test_db):
        _insert_capability(test_db, "aws-admin")
        rows = list_capabilities()
        assert rows[0]["kind"] == "provider_access"
        assert rows[0]["state"] == "configured_unverified"
        assert rows[0]["verified_at"] is None
        assert rows[0]["verified_source"] is None

    def test_stamped_verified_at_reads_verified(self, test_db):
        stamp = _iso(5)
        _insert_capability(test_db, "docker", verified_at=stamp)
        rows = list_capabilities()
        assert rows[0]["state"] == "ready"
        assert rows[0]["verified_at"] == stamp
        assert rows[0]["verified_source"] == "capability"

    def test_test_machine_is_a_ready_test_resource(self, test_db):
        _insert_capability(
            test_db,
            "test-machine",
            settings=(
                '{"resource_name":"mac-mini-lab","host":"mac",'
                '"user":"yoke","operating_notes":""}'
            ),
            verified_at=_iso(2),
        )
        row = list_capabilities()[0]
        assert (row["kind"], row["state"]) == ("test_resource", "ready")
        assert row["display_type"] == "test-mac"
        assert row["active_item_ref"] is None
        assert row["used_by_summary"].startswith("Machine methods ×")

    def test_test_machine_in_use_names_the_claimed_item(self, test_db):
        _insert_capability(
            test_db,
            "test-machine",
            settings=(
                '{"resource_name":"mac-mini-lab","host":"mac",'
                '"user":"yoke","operating_notes":""}'
            ),
            verified_at=_iso(2),
        )
        item = insert_item(
            test_db,
            id=41,
            project_sequence=2001,
            title="Prove the installer campaign",
        )
        now = _iso()
        test_db.execute(
            "CREATE TABLE coordination_leases("
            "project_id INTEGER NOT NULL,"
            "lease_key TEXT NOT NULL,"
            "session_id TEXT NOT NULL,"
            "acquired_at TEXT NOT NULL,"
            "heartbeat_at TEXT,"
            "released_at TEXT"
            ")"
        )
        test_db.execute(
            "INSERT INTO harness_sessions("
            "session_id,executor,provider,model,workspace,project_id,"
            "offered_at,last_heartbeat"
            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                "session-machine",
                "codex",
                "openai",
                "gpt",
                "/tmp/yoke-capability-test",
                1,
                now,
                now,
            ),
        )
        test_db.execute(
            "INSERT INTO work_claims("
            "session_id,target_kind,item_id,claimed_at,last_heartbeat"
            ") VALUES (%s,'item',%s,%s,%s)",
            ("session-machine", int(item["id"]), now, now),
        )
        test_db.execute(
            "INSERT INTO coordination_leases("
            "project_id,lease_key,session_id,acquired_at,heartbeat_at"
            ") VALUES (%s,%s,%s,%s,%s)",
            (
                1,
                "QA_HOST:mac-mini-lab",
                "session-machine",
                now,
                now,
            ),
        )
        test_db.commit()

        row = list_capabilities()[0]
        assert row["state"] == "in_use"
        assert row["active_item_ref"] == "YOK-2001"


class TestGithubFreshnessOverlay:
    def test_binding_stamp_becomes_the_github_row_surrogate(self, test_db):
        binding_stamp = _iso(10)
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db,
            binding_verified_at=binding_stamp,
            installation_verified_at=_iso(60),
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] == binding_stamp
        assert rows[0]["verified_source"] == "repo-binding"
        assert rows[0]["state"] == "ready"

    def test_installation_stamp_serves_when_newer_than_binding(self, test_db):
        installation_stamp = _iso(3)
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db,
            binding_verified_at=_iso(90),
            installation_verified_at=installation_stamp,
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] == installation_stamp
        assert rows[0]["verified_source"] == "repo-binding"

    def test_github_without_stamps_stays_configured_unverified(self, test_db):
        _insert_capability(test_db, "github")
        _insert_github_binding(test_db)
        rows = list_capabilities()
        assert rows[0]["verified_at"] is None
        assert rows[0]["verified_source"] is None
        assert rows[0]["state"] == "configured_unverified"

    def test_overlay_never_leaks_onto_other_types(self, test_db):
        _insert_capability(test_db, "github")
        _insert_capability(test_db, "aws-admin")
        _insert_github_binding(test_db, binding_verified_at=_iso(1))
        by_type = {row["type"]: row for row in list_capabilities()}
        assert by_type["github"]["state"] == "ready"
        assert by_type["aws-admin"]["state"] == "configured_unverified"
        assert by_type["aws-admin"]["verified_at"] is None

    def test_suspended_installation_never_reads_verified(self, test_db):
        # Both stamps were earned through the installation's credential
        # channel; a suspended installation severs it, so neither stamp
        # overlays — the row must agree with the binding status read's
        # automation-unavailable verdict instead of contradicting it.
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db,
            binding_verified_at=_iso(10),
            installation_verified_at=_iso(3),
            installation_status="suspended",
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] is None
        assert rows[0]["verified_source"] is None
        assert rows[0]["state"] == "configured_unverified"

    def test_deleted_installation_never_reads_verified(self, test_db):
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db,
            binding_verified_at=_iso(10),
            installation_verified_at=_iso(3),
            installation_status="deleted",
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] is None
        assert rows[0]["state"] == "configured_unverified"

    def test_suspension_gates_only_the_overlay_source(self, test_db):
        # The capability row's own stamp is a different provenance: it
        # never flowed through the installation, so a suspended
        # installation does not erase it.
        stamp = _iso(30)
        _insert_capability(test_db, "github", verified_at=stamp)
        _insert_github_binding(
            test_db,
            binding_verified_at=_iso(5),
            installation_status="suspended",
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] == stamp
        assert rows[0]["verified_source"] == "capability"
        assert rows[0]["state"] == "ready"
