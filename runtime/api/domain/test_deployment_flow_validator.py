"""Unit tests for ``yoke_core.domain.deployment_flow_validator``."""

from __future__ import annotations

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_flow_validator import (
    list_active_flow_ids,
    list_registered_flow_ids,
    normalize_deployment_flow_value,
    validate_and_lookup_flow_project,
)


def _seed_conn():
    conn = connect()
    conn.execute(
        "CREATE TEMP TABLE projects "
        "(id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
        "public_item_prefix TEXT NOT NULL DEFAULT 'YOK')"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES "
        "(1, 'yoke', 'Yoke'), (2, 'buzz', 'Buzz')"
    )
    conn.execute(
        "CREATE TEMP TABLE deployment_flows "
        "(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'active')"
    )
    for row in [
        ("yoke-internal", 1),
        ("yoke-prod-release", 1),
        ("buzz-internal", 2),
        ("buzz-prod-release", 2),
    ]:
        conn.execute("INSERT INTO deployment_flows (id, project_id) VALUES (%s, %s)", row)
    return conn


def test_list_registered_flow_ids_no_filter_returns_all_sorted():
    conn = _seed_conn()
    assert list_registered_flow_ids(conn) == [
        "buzz-internal",
        "buzz-prod-release",
        "yoke-internal",
        "yoke-prod-release",
    ]


def test_list_registered_flow_ids_filtered_by_project():
    conn = _seed_conn()
    assert list_registered_flow_ids(conn, "yoke") == [
        "yoke-internal",
        "yoke-prod-release",
    ]
    assert list_registered_flow_ids(conn, "buzz") == [
        "buzz-internal",
        "buzz-prod-release",
    ]


def test_list_registered_flow_ids_unknown_project_is_empty():
    conn = _seed_conn()
    assert list_registered_flow_ids(conn, "unknown") == []


def test_disabled_flows_remain_registered_but_are_not_assignable():
    conn = _seed_conn()
    conn.execute(
        "UPDATE deployment_flows SET status='disabled' "
        "WHERE id='yoke-prod-release'"
    )
    assert "yoke-prod-release" in list_registered_flow_ids(conn, "yoke")
    assert "yoke-prod-release" not in list_active_flow_ids(conn, "yoke")
    flow_project, err = validate_and_lookup_flow_project(
        conn, "yoke-prod-release", "yoke"
    )
    assert flow_project is None
    assert "disabled" in str(err)
    assert "yoke-internal" in str(err)


def test_validate_returns_none_for_none_value():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, None)
    assert flow_project is None
    assert err is None


def test_validate_returns_none_for_empty_value():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "")
    assert flow_project is None
    assert err is None


def test_validate_returns_none_for_null_sentinel():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "null")
    assert flow_project is None
    assert err is None


def test_normalize_deployment_flow_value_collapses_null_sentinel():
    assert normalize_deployment_flow_value("null") is None
    assert normalize_deployment_flow_value("") == ""
    assert normalize_deployment_flow_value("yoke-internal") == "yoke-internal"


def test_validate_returns_flow_project_for_registered_id():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "yoke-internal")
    assert flow_project == "yoke"
    assert err is None


def test_validate_rejects_unregistered_value_with_alternatives():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "garbage")
    assert flow_project is None
    assert err is not None
    assert "garbage" in err
    assert "is not registered" in err
    # Without project filter, list every registered flow.
    assert "yoke-internal" in err
    assert "buzz-internal" in err


def test_validate_rejects_literal_none_string():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "none")
    assert flow_project is None
    assert err is not None
    assert "'none'" in err


def test_validate_rejects_unregistered_value_filtered_by_project():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "garbage", "yoke")
    assert flow_project is None
    assert err is not None
    assert "project 'yoke'" in err
    assert "yoke-internal" in err
    # Project-filtered alternatives should NOT mix in other projects' flows.
    assert "buzz-internal" not in err


def test_validate_with_project_filter_no_registered_flows_says_so():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(conn, "garbage", "ghost-project")
    assert flow_project is None
    assert err is not None
    assert "ghost-project" in err
    assert "No deployment flows are registered" in err


def test_validate_passes_registered_id_with_project_filter():
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(
        conn, "yoke-internal", "yoke"
    )
    assert flow_project == "yoke"
    assert err is None


def test_validate_with_project_filter_does_not_cross_project_check():
    """Project filter only narrows the alternatives list in the error.

    A registered flow that exists in another project still passes the
    registry check; cross-project mismatch is enforced separately by the
    mutation-layer same-project gate.
    """
    conn = _seed_conn()
    flow_project, err = validate_and_lookup_flow_project(
        conn, "buzz-internal", "yoke"
    )
    assert flow_project == "buzz"
    assert err is None
