"""Registration contract for browser-readable and operator mutation calls."""

from __future__ import annotations

from yoke_core.ui import server as ui_server


class TestRegistrationShape:
    def test_latch_read_declares_exactly_the_latch_side_effect(self):
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
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
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        assert ui_server.UI_MUTATION_FUNCTION_ALLOWLIST == {
            "overview.module.dismiss",
            "overview.module.restore",
            "workflows.current.set",
            "workflows.policy_defaults.publish",
            "workflows.testing_default.set",
            "workflows.delivery_default.set",
            "workflows.approval_defaults.publish",
            "workflows.canon_update.apply",
            "workflows.canon_update.apply_all",
            "workflows.canon_follow.set",
            "workflow.execution_instruction.create",
            "workflow.execution_instruction.update",
            "workflow.execution_instruction.set_scope",
            "workflow.execution_instruction.delete",
            "test_machine.settings_replace",
            "test_machine.verify",
            "decision_requests.resolve",
            "qa.case.waive",
            "items.create",
            "sessions.reclaim_stale",
            "organizations.settings.merge",
            "session_control.message.send",
            "session_control.message.acknowledge",
            "session_control.message.cancel",
            "session_control.launch.create",
            "session_control.launch.cancel",
            "session_control.launch.reconcile",
            "session_control.launch.retry",
            "strategy.revision.restore",
            "deployment_runs.terminalize",
            "deployment_flows.update_stages",
        }
        assert not (
            ui_server.UI_MUTATION_FUNCTION_ALLOWLIST
            & ui_server.UI_READ_FUNCTION_ALLOWLIST
        )
        for function_id in ui_server.UI_MUTATION_FUNCTION_ALLOWLIST:
            entry = lookup(function_id)
            assert entry is not None, function_id
            assert entry.claim_required_kind is None
        assert "actor_required" in lookup("overview.module.dismiss").guardrails
        assert (
            "expected_current_version"
            in lookup("workflows.policy_defaults.publish").guardrails
        )
