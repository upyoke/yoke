"""Parity tests — import structure and deployment-run domain regression."""

from __future__ import annotations


# ===========================================================================
# Group 5: Import structure and startup regression
# ===========================================================================


class TestImportStructure:
    """Verify the package structure supports clean imports without sys.path hacks."""

    def test_domain_importable_from_package(self):
        """All domain modules should be importable via package path."""
        from yoke_core.domain import lifecycle as lc
        from yoke_core.domain import approval as ap
        from yoke_core.domain import board as bd
        from yoke_core.domain import queries as qr
        from yoke_core.domain import runs as rn

        # Spot check: each module has its key exports
        assert hasattr(lc, "ItemStatus")
        assert hasattr(lc, "ALL_ITEM_STATUSES")
        assert hasattr(ap, "HaltState")
        assert hasattr(ap, "resolve_approval")
        assert hasattr(bd, "status_to_board_bucket")
        assert hasattr(bd, "project_board")
        assert hasattr(qr, "ItemFilter")
        assert hasattr(qr, "build_where_clause")
        assert hasattr(rn, "RunStatus")
        assert hasattr(rn, "advance_run_stage")

    def test_domain_init_provides_docstring(self):
        """Domain __init__.py should have a module docstring."""
        from yoke_core import domain
        assert domain.__doc__ is not None
        assert "domain" in domain.__doc__.lower()

    def test_main_module_importable(self):
        """The main FastAPI app should be importable via package path."""
        from yoke_core.api.main import app as yoke_app
        assert yoke_app is not None
        assert yoke_app.title == "Yoke API"

    def test_service_client_importable(self):
        """The service client module should be importable via package path."""
        from yoke_core.api.service_client import COMMANDS
        assert "approve-check" in COMMANDS
        assert "active-queue" in COMMANDS
        assert "classify-status" in COMMANDS
        assert "validate-status" in COMMANDS
        assert "validate-transition" in COMMANDS


# ===========================================================================
# Group 6: Deployment-run domain-layer regression
# ===========================================================================


class TestDeploymentRunRegression:
    """Regression tests for deployment-run domain semantics."""

    def test_active_run_status_constants(self):
        """Active and terminal run status sets should be disjoint and complete."""
        from yoke_core.domain.runs import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, RunStatus

        all_run_statuses = {s.value for s in RunStatus}
        assert ACTIVE_RUN_STATUSES & TERMINAL_RUN_STATUSES == set(), (
            "Active and terminal sets must be disjoint"
        )
        assert ACTIVE_RUN_STATUSES | TERMINAL_RUN_STATUSES == all_run_statuses, (
            "Active + terminal must cover all run statuses"
        )

    def test_advance_run_stage_forward(self):
        """Advancing an active run should return the next stage."""
        from yoke_core.domain.runs import DeploymentRun, advance_run_stage

        run = DeploymentRun(
            id="test-run", project="yoke", flow="test-flow",
            status="executing", current_stage="stage-1",
        )
        result = advance_run_stage(run, ["stage-1", "stage-2", "stage-3"])
        assert result.advanced is True
        assert result.next_stage == "stage-2"

    def test_advance_run_stage_to_complete(self):
        """Advancing past the last stage should return 'complete'."""
        from yoke_core.domain.runs import DeploymentRun, advance_run_stage

        run = DeploymentRun(
            id="test-run", project="yoke", flow="test-flow",
            status="executing", current_stage="stage-3",
        )
        result = advance_run_stage(run, ["stage-1", "stage-2", "stage-3"])
        assert result.advanced is True
        assert result.next_stage == "complete"

    def test_advance_terminal_run_rejected(self):
        """Advancing a terminal run should fail."""
        from yoke_core.domain.runs import DeploymentRun, advance_run_stage

        run = DeploymentRun(
            id="test-run", project="yoke", flow="test-flow",
            status="succeeded", current_stage="stage-1",
        )
        result = advance_run_stage(run, ["stage-1", "stage-2"])
        assert result.advanced is False
        assert "terminal" in result.error.lower()
