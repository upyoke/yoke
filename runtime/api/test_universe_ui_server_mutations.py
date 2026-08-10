"""Local UI proxy coverage for the narrow operator mutation surfaces.

Pins the bounded mutation allowlist, the documented latch exception on the
read allowlist, and the operator-actor resolution rules.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yoke_core.domain.actors import seed_human_actor, set_actor_label
from runtime.api.workflow_version_test_helpers import current_workflow_version
from yoke_core.ui import local_operator_actor, server as ui_server


_TOKEN = "test-session-token-value"


@pytest.fixture()
def ui_client():
    with TestClient(ui_server.create_ui_app(_TOKEN)) as client:
        yield client


def _call(ui_client, envelope):
    return ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json=envelope,
    )


class TestRegistrationShape:
    def test_latch_read_declares_exactly_the_latch_side_effect(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        assert ui_server.UI_ACTIVATION_LATCH_FUNCTIONS <= (
            ui_server.UI_READ_FUNCTION_ALLOWLIST
        )
        for function_id in ui_server.UI_ACTIVATION_LATCH_FUNCTIONS:
            entry = lookup(function_id)
            assert entry is not None, function_id
            assert entry.side_effects == ("overview_activation_facts_insert",)
            assert entry.claim_required_kind is None

    def test_mutation_allowlist_is_the_bounded_browser_operation_roster(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        assert ui_server.UI_MUTATION_FUNCTION_ALLOWLIST == {
            "overview.module.dismiss", "overview.module.restore",
            "workflows.current.set", "workflows.policy_defaults.publish",
            "workflows.testing_default.set",
            "workflows.delivery_default.set",
            "workflows.approval_defaults.publish",
            # Taking a published workflow update is an operator decision made
            # in the browser, next to the diff that explains it. It publishes
            # a version like its siblings above, and refuses rather than
            # resolving when the merge conflicts with local edits. Taking
            # every pending update at once, and turning automatic adoption
            # back on, are the same decision at a different grain.
            "workflows.canon_update.apply",
            "workflows.canon_update.apply_all",
            "workflows.canon_follow.set",
            # Execution instructions are operator-authored in the browser,
            # next to the workflow roster they scope over.
            "workflow.execution_instruction.create",
            "workflow.execution_instruction.update",
            "workflow.execution_instruction.set_scope",
            "workflow.execution_instruction.delete",
            "test_machine.settings_replace", "test_machine.verify",
            "decision_requests.resolve",
            "notifications.read", "notifications.read_all",
            "qa.case.rerun", "qa.case.waive",
            "items.create",
            "sessions.reclaim_stale",
            "strategy.revision.restore",
            "deployment_runs.terminalize",
        }
        assert not (
            ui_server.UI_MUTATION_FUNCTION_ALLOWLIST
            & ui_server.UI_READ_FUNCTION_ALLOWLIST
        )
        for function_id in ui_server.UI_MUTATION_FUNCTION_ALLOWLIST:
            entry = lookup(function_id)
            assert entry is not None, function_id
            assert entry.claim_required_kind is None
        assert "actor_required" in lookup(
            "overview.module.dismiss"
        ).guardrails
        assert "expected_current_version" in lookup(
            "workflows.policy_defaults.publish"
        ).guardrails


class TestOperatorActorResolution:
    def test_sole_human_resolves(self, test_db):
        resolved = local_operator_actor.resolve_local_operator_actor()
        row = test_db.execute(
            "SELECT id FROM actors WHERE kind = 'human'"
        ).fetchone()
        assert resolved == int(row[0])

    def test_ambiguous_humans_without_login_match_resolve_to_nobody(
        self, test_db, monkeypatch,
    ):
        seed_human_actor(test_db)
        monkeypatch.setattr(
            local_operator_actor, "_os_login", lambda: "nobody-known",
        )
        assert local_operator_actor.resolve_local_operator_actor() is None

    def test_login_label_disambiguates_among_humans(
        self, test_db, monkeypatch,
    ):
        second = seed_human_actor(test_db)
        set_actor_label(test_db, second, "operator-login")
        monkeypatch.setattr(
            local_operator_actor, "_os_login", lambda: "operator-login",
        )
        assert local_operator_actor.resolve_local_operator_actor() == second


class TestProxyMutations:
    def test_unlisted_mutation_stays_refused(self, ui_client):
        response = _call(
            ui_client, {"function": "items.structured_field.replace"},
        )
        assert response.status_code == 403
        allowed = response.json()["error"]["allowed"]
        assert "overview.module.dismiss" in allowed
        assert "overview.activation.get" in allowed

    def test_dismiss_and_restore_act_as_the_operator(self, ui_client, test_db):
        dismissed = _call(ui_client, {
            "function": "overview.module.dismiss",
            "payload": {"module_key": "connect_harness"},
        })
        assert dismissed.status_code == 200
        envelope = dismissed.json()
        assert envelope["success"] is True, envelope
        assert envelope["result"] == {
            "module_key": "connect_harness", "dismissed": True,
        }
        operator = test_db.execute(
            "SELECT id FROM actors WHERE kind = 'human'"
        ).fetchone()[0]
        row = test_db.execute(
            "SELECT actor_id, pref_key FROM actor_ui_preferences"
        ).fetchone()
        assert int(row[0]) == int(operator)
        assert row[1] == "overview.module.dismissed.connect_harness"

        # The activation read reflects the same operator resolution.
        activation = _call(ui_client, {
            "function": "overview.activation.get",
            "payload": {"host_facts": {"machine_connected": True}},
        }).json()
        assert activation["success"] is True
        assert activation["result"]["dismiss_available"] is True
        by_key = {
            module["key"]: module
            for module in activation["result"]["modules"]
        }
        assert by_key["connect_harness"]["dismissed"] is True

        restored = _call(ui_client, {
            "function": "overview.module.restore",
            "payload": {"module_key": "connect_harness"},
        })
        assert restored.json()["result"]["dismissed"] is False
        remaining = test_db.execute(
            "SELECT COUNT(*) FROM actor_ui_preferences"
        ).fetchone()[0]
        assert int(remaining) == 0

    def test_deployment_run_terminalization_is_attributed_and_audited(
        self, ui_client, test_db,
    ):
        from yoke_core.domain.actor_permissions import (
            ROLE_ADMIN,
            grant_actor_org_role,
            seed_roles_and_permissions,
        )

        seed_roles_and_permissions(test_db)
        operator = int(local_operator_actor.resolve_local_operator_actor())
        org_id = int(test_db.execute(
            "SELECT id FROM organizations ORDER BY id LIMIT 1"
        ).fetchone()[0])
        grant_actor_org_role(
            test_db,
            actor_id=operator,
            org_id=org_id,
            role_name=ROLE_ADMIN,
            granted_by_actor_id=operator,
        )
        test_db.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, stages, created_at) "
            "VALUES ('ui-terminalize', 1, 'UI terminalize', '[]', "
            "'2026-08-05T00:00:00Z')"
        )
        test_db.execute(
            "INSERT INTO deployment_runs "
            "(id, project_id, flow, status, created_at) "
            "VALUES ('run-ui-terminalize', 1, 'ui-terminalize', "
            "'executing', '2026-08-05T00:00:00Z')"
        )
        test_db.commit()

        response = _call(ui_client, {
            "function": "deployment_runs.terminalize",
            "target": {
                "kind": "workflow_run",
                "workflow_run_id": "run-ui-terminalize",
            },
            "payload": {
                "disposition": "cancelled",
                "reason": "No external execution remains",
            },
        })
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True, envelope
        assert envelope["result"]["terminalized_by_actor_id"] == operator
        event = test_db.execute(
            "SELECT severity, actor_id FROM events WHERE event_id=%s",
            (envelope["result"]["event_id"],),
        ).fetchone()
        assert event[0] == "STATUS"
        assert int(event[1]) == operator

    def test_workflow_default_publish_acts_as_org_admin(
        self, ui_client, test_db,
    ):
        converged = current_workflow_version(test_db, "dash")
        from yoke_core.domain.actor_permissions import (
            ROLE_ADMIN,
            grant_actor_org_role,
            seed_roles_and_permissions,
        )

        seed_roles_and_permissions(test_db)
        operator = int(
            local_operator_actor.resolve_local_operator_actor()
        )
        org_id = int(
            test_db.execute(
                "SELECT id FROM organizations ORDER BY id LIMIT 1"
            ).fetchone()[0]
        )
        grant_actor_org_role(
            test_db,
            actor_id=operator,
            org_id=org_id,
            role_name=ROLE_ADMIN,
            granted_by_actor_id=operator,
        )
        test_db.commit()
        survey_response = _call(ui_client, {
            "function": "workflows.policy_defaults.publish",
            "payload": {
                "workflow_id": "dash",
                "expected_current_version": converged,
                "path_survey_default": False,
            },
        })
        assert survey_response.status_code == 200
        survey_envelope = survey_response.json()
        assert survey_envelope["success"] is True, survey_envelope
        response = _call(ui_client, {
            "function": "workflows.policy_defaults.publish",
            "payload": {
                "workflow_id": "dash",
                "expected_current_version": survey_envelope["result"]["version"],
                "path_claims_default": True,
            },
        })
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True, envelope
        expected_version = converged + 2
        assert envelope["result"]["version"] == expected_version
        row = test_db.execute(
            "SELECT published_by_actor_id FROM workflow_versions "
            "WHERE workflow_id = 'dash' AND version = %s",
            (expected_version,),
        ).fetchone()
        assert int(row[0]) == operator

    def test_unresolved_operator_refuses_writes_but_reads_still_serve(
        self, ui_client, test_db, monkeypatch,
    ):
        seed_human_actor(test_db)
        monkeypatch.setattr(
            local_operator_actor, "_os_login", lambda: "nobody-known",
        )
        refused = _call(ui_client, {
            "function": "overview.module.dismiss",
            "payload": {"module_key": "connect_harness"},
        })
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "operator_actor_unresolved"

        activation = _call(ui_client, {"function": "overview.activation.get"})
        assert activation.status_code == 200
        envelope = activation.json()
        assert envelope["success"] is True
        assert envelope["result"]["dismiss_available"] is False

    def test_latch_persists_through_the_proxy(self, ui_client, test_db):
        first = _call(ui_client, {
            "function": "overview.activation.get",
            "payload": {"host_facts": {"machine_connected": True}},
        }).json()
        wizard = first["result"]["modules"][0]
        assert wizard["state"] == "activated"
        row = test_db.execute(
            "SELECT module_key FROM overview_activation_facts"
        ).fetchall()
        assert [r[0] for r in row] == ["finish_installation_wizard"]
