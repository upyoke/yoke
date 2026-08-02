"""Facade exports for workflow-aware product adapters."""

from yoke_cli.commands.adapters import qa_catalog, test_machine, workflow_mechanics


PRODUCT_ADAPTER_EXPORTS = {
    name: getattr(module, name)
    for module, names in (
        (
            qa_catalog,
            (
                "qa_activity_list",
                "qa_artifact_read",
                "qa_method_get",
                "qa_method_list",
                "qa_plan_cases_replace",
                "qa_plan_create",
                "qa_plan_get",
                "qa_plan_item_attach",
                "qa_plan_list",
                "qa_plan_materialize_for_item",
                "qa_plan_rematerialize",
                "qa_plan_project_default_set",
            ),
        ),
        (
            test_machine,
            (
                "test_machine_get",
                "test_machine_settings_replace",
                "test_machine_verify",
            ),
        ),
        (
            workflow_mechanics,
            (
                "workflows_approval_defaults_publish",
                "workflows_delivery_default_set",
                "workflows_mechanics_get",
                "workflows_testing_default_set",
            ),
        ),
    )
    for name in names
}


__all__ = ["PRODUCT_ADAPTER_EXPORTS"]
