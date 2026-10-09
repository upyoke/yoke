"""Read scopes never retain stale schema or mutable composition facts."""

from unittest.mock import Mock
import pytest
from yoke_core.domain.schema_read_scope import composition_reads, shared_read
from yoke_core.domain.schema_common_postgres import _postgres_column_exists


def test_nested_scopes_share_and_exit_discards_even_after_refusal():
    conn = object()
    reader = Mock(side_effect=["before", "after"])
    with pytest.raises(ValueError), composition_reads():
        assert shared_read(conn, "source", reader) == "before"
        with composition_reads():
            assert shared_read(conn, "source", reader) == "before"
        raise ValueError("refused")
    with composition_reads():
        assert shared_read(conn, "source", reader) == "after"
    assert reader.call_count == 2


def test_connections_do_not_share_schema_catalog_answers():
    first, second = object(), object()
    reader = Mock(side_effect=["first", "second"])
    with composition_reads():
        assert shared_read(first, "columns", reader) == "first"
        assert shared_read(second, "columns", reader) == "second"
    assert reader.call_count == 2


def test_column_probes_batch_within_scope_only():
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [("id",), ("flow",)]
    with composition_reads():
        assert _postgres_column_exists(conn, "runs", "id")
        assert _postgres_column_exists(conn, "runs", "flow")
        assert not _postgres_column_exists(conn, "runs", "absent")
    assert conn.execute.call_count == 1
    conn.execute.return_value.fetchall.return_value = [("id",), ("new_column",)]
    with composition_reads():
        assert _postgres_column_exists(conn, "runs", "new_column")
    assert conn.execute.call_count == 2


def test_bound_source_write_invalidates_previously_read_source():
    from yoke_core.domain.schema_read_scope import discard_read

    conn = object()
    reader = Mock(side_effect=["unbound", "pinned"])
    with composition_reads():
        assert shared_read(conn, ("run_source", "run"), reader) == "unbound"
        discard_read(conn, ("run_source", "run"))
        assert shared_read(conn, ("run_source", "run"), reader) == "pinned"
    assert reader.call_count == 2


def test_freeze_shares_one_custody_resolution_between_refusal_checks():
    from unittest.mock import patch
    from yoke_core.domain import deployment_run_composition_freeze as freeze

    conn = Mock()
    conn.execute.return_value.fetchone.return_value = ("flow", "a" * 40, None, 1, "[]")
    conn.execute.return_value.fetchall.return_value = []
    custody = object()
    with (
        patch.object(freeze, "requires_release_admission", return_value=True),
        patch.object(freeze, "_require_schema"),
        patch.object(freeze, "snapshot_flow_requirements", return_value="{}"),
        patch.object(freeze, "record_bound_sources"),
        patch.object(freeze, "record_carried_work", return_value={}),
        patch(
            "yoke_core.domain.deployment_run_unheld_candidates.resolve_candidate_custody",
            return_value=custody,
        ) as walk,
        patch(
            "yoke_core.domain.deployment_run_carried_membership_refusal.carried_membership_refusal",
            return_value=None,
        ) as membership,
        patch(
            "yoke_core.domain.deployment_member_run_coverage.unclosable_final_member_refusal",
            return_value=None,
        ) as completion,
    ):
        assert freeze.freeze_run_composition(conn, "run-freeze")["frozen_at"]
    walk.assert_called_once_with(conn, "run-freeze")
    assert membership.call_args.kwargs["custody"] is custody
    assert completion.call_args.kwargs["custody"] is custody
