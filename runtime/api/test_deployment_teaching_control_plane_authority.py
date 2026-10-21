"""Deployment recipes never default to a database-admin connection."""

from __future__ import annotations

from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX
from yoke_core.domain.deploy_pipeline_environment import (
    CONTROL_PLANE_ENV_PLACEHOLDER,
    run_not_found_message,
    watch_deploy_command,
)

DB_ADMIN_LABEL = DB_ADMIN_ENV_SUFFIX.lstrip("-")


class TestTheExecuteRecipeRuntimeTeaching:
    """The recipes the prepared-run hand-off and the Dash gate hand out."""

    def test_a_resolved_connection_is_named_as_selected(self) -> None:
        assert (
            watch_deploy_command("run-20260908-001", "prod")
            == "yoke --env prod watch deploy -- run-20260908-001"
        )

    def test_an_unresolved_connection_teaches_the_shape(self) -> None:
        recipe = watch_deploy_command("run-20260908-001")
        assert CONTROL_PLANE_ENV_PLACEHOLDER in recipe
        assert DB_ADMIN_LABEL not in recipe

    def test_an_admin_connection_selected_by_the_operator_is_preserved(self) -> None:
        """Naming it is wrong only as a default, never as the active choice."""
        recipe = watch_deploy_command("run-20260908-001", "prod-db-admin")
        assert recipe == "yoke --env prod-db-admin watch deploy -- run-20260908-001"

    def test_a_missing_run_is_not_redirected_to_database_authority(self) -> None:
        message = run_not_found_message("run-20260908-001")
        assert DB_ADMIN_LABEL not in message
        assert "`--env` selecting that control plane" in message
