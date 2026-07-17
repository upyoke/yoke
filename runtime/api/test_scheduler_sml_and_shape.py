"""SML coherence and SchedulerResult shape tests for yoke_core.domain.scheduler."""
from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain import db_backend
from yoke_core.domain.scheduler import (
    _compute_sml_state,
    compute_schedule,
)
from yoke_core.domain.strategy_docs_defaults import DEFAULT_STRATEGY_DOC_SLUGS

# Re-export the fixture so pytest discovers it in this module.
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    scheduler_db,
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestSMLState:
    """Verify truthful SML computation against strategy_docs rows."""

    def test_all_docs_live_coherent(self, scheduler_db):
        """The fixture seeds all default docs, so coherent=True."""
        sml = _compute_sml_state(scheduler_db["conn"], [1])
        assert sml.coherent is True

    def test_missing_docs_incoherent(self, scheduler_db):
        """A project with no strategy_docs rows is incoherent."""
        conn = scheduler_db["conn"]
        conn.execute("DELETE FROM strategy_docs")
        sml = _compute_sml_state(conn, [1])
        assert sml.coherent is False

    def test_partial_docs_incoherent(self, scheduler_db):
        """A project missing one default doc row is incoherent."""
        conn = scheduler_db["conn"]
        p = _placeholder(conn)
        conn.execute(
            f"DELETE FROM strategy_docs WHERE slug = {p}",
            (DEFAULT_STRATEGY_DOC_SLUGS[0],),
        )
        sml = _compute_sml_state(conn, [1])
        assert sml.coherent is False

    def test_archived_doc_incoherent(self, scheduler_db):
        """An archived default doc no longer counts as live."""
        conn = scheduler_db["conn"]
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE strategy_docs SET archived_at = '2026-03-02' WHERE slug = {p}",
            (DEFAULT_STRATEGY_DOC_SLUGS[0],),
        )
        sml = _compute_sml_state(conn, [1])
        assert sml.coherent is False

    def test_empty_scope_coherent(self, scheduler_db):
        """An empty project scope has nothing to be incoherent about."""
        sml = _compute_sml_state(scheduler_db["conn"], [])
        assert sml.coherent is True


class TestSchedulerResultShape:
    """Verify SchedulerResult contract after payoff-model removals."""

    def test_schedule_result_no_graph_stale(self, scheduler_db):
        """SchedulerResult no longer carries graph_stale."""
        conn = scheduler_db["conn"]
        result = compute_schedule(conn, project_scope=["yoke"])
        assert not hasattr(result, "graph_stale")

    @patch("yoke_core.domain.scheduler._emit_frontier_step_selected")
    def test_schedule_still_emits_frontier_step_selected(self, mock_emit, scheduler_db):
        """FrontierStepSelected emission survives the graph_stale removal."""
        conn = scheduler_db["conn"]
        result = compute_schedule(conn, project_scope=["yoke"])
        mock_emit.assert_called_once_with(conn, result, None)
