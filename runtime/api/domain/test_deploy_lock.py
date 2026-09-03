"""One session drives a project's deployments; the rest are refused.

The lock exists because two boxes with owner-only connections could each
drive a run against the same project — a stage promotion overtaking the
production promotion it was meant to precede. These tests pin the four
facts an operator depends on: no lock refuses, the holder proceeds, a
second taker is refused with the first named, and a release frees it.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import coordination_claims
from yoke_core.domain.coordination_claim_keys import (
    CoordinationKeyError,
    key_for_target,
    target_for_key,
)
from yoke_core.domain.deploy_lock import (
    DeployLockHeldElsewhereError,
    DeployLockNotHeldError,
    acquire_command,
    deploy_lock_key,
    release_command,
    require_deploy_lock,
)
from yoke_core.domain.work_claim_targets import (
    make_deploy_serialization_target,
    is_sticky,
)
from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    deploy_target,
    seed_project,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

DRIVER = "sess-driver"
SECOND = "sess-second"
SLUG = "yoke"


@pytest.fixture()
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        conn = connect_test_db(path)
        try:
            seed_project(conn, PROJECT_YOKE, SLUG)
            seed_session(conn, DRIVER)
            seed_session(conn, SECOND)
        finally:
            conn.close()
        yield path


def _take(conn, session_id: str = DRIVER):
    return coordination_claims.acquire(
        conn, deploy_target(), session_id, reason="deploy-lock"
    )


def test_key_renders_from_the_slug_and_round_trips(db_path):
    target = make_deploy_serialization_target(PROJECT_YOKE, SLUG)
    assert key_for_target(target) == f"DEPLOY:{SLUG}"
    assert deploy_lock_key(SLUG) == f"DEPLOY:{SLUG}"
    assert (
        target_for_key(
            f"DEPLOY:{SLUG}", project_id=PROJECT_YOKE, project_slug=SLUG
        )
        == target
    )


def test_key_naming_another_project_is_refused_not_silently_retargeted():
    with pytest.raises(CoordinationKeyError) as caught:
        target_for_key(
            "DEPLOY:platform", project_id=PROJECT_YOKE, project_slug=SLUG
        )
    assert "platform" in str(caught.value)
    assert f"DEPLOY:{SLUG}" in str(caught.value)


def test_the_kind_is_sticky_so_no_sweep_reclaims_a_running_deploy():
    assert is_sticky(deploy_target().kind)


def test_create_refuses_without_the_lock_and_names_the_recipe(db_path):
    conn = connect_test_db(db_path)
    try:
        with pytest.raises(DeployLockNotHeldError) as caught:
            require_deploy_lock(
                conn, SLUG, session_id=DRIVER, operation="deployment_runs.create"
            )
    finally:
        conn.close()
    message = str(caught.value)
    assert "deployment_runs.create refused" in message
    assert acquire_command(SLUG) in message
    assert release_command(SLUG) in message


def test_the_holder_proceeds(db_path):
    conn = connect_test_db(db_path)
    try:
        taken = _take(conn)
        held = require_deploy_lock(
            conn, SLUG, session_id=DRIVER, operation="deployment_runs.create"
        )
        assert held.id == taken.id
    finally:
        conn.close()


def test_a_second_session_is_refused_with_the_holder_named(db_path):
    conn = connect_test_db(db_path)
    try:
        _take(conn)
        with pytest.raises(DeployLockHeldElsewhereError) as caught:
            require_deploy_lock(
                conn,
                SLUG,
                session_id=SECOND,
                operation="deployment run execution",
            )
    finally:
        conn.close()
    message = str(caught.value)
    assert DRIVER in message
    assert "coordination-claim release" in message


def test_a_sessionless_caller_is_told_where_a_session_comes_from(db_path):
    conn = connect_test_db(db_path)
    try:
        _take(conn)
        with pytest.raises(DeployLockHeldElsewhereError) as caught:
            require_deploy_lock(
                conn, SLUG, session_id=None, operation="deployment_runs.create"
            )
    finally:
        conn.close()
    message = str(caught.value)
    assert "resolved no harness session" in message
    assert "yoke sessions begin --help" in message


def test_a_second_acquire_is_refused_at_the_exclusivity_index(db_path):
    conn = connect_test_db(db_path)
    try:
        _take(conn)
        with pytest.raises(coordination_claims.CoordinationClaimHeldError):
            _take(conn, SECOND)
    finally:
        conn.close()


def test_the_unit_is_the_project_id_so_a_renamed_slug_still_conflicts(db_path):
    conn = connect_test_db(db_path)
    try:
        _take(conn)
        renamed = make_deploy_serialization_target(PROJECT_YOKE, "yoke-renamed")
        with pytest.raises(coordination_claims.CoordinationClaimHeldError):
            coordination_claims.acquire(conn, renamed, SECOND)
    finally:
        conn.close()


def test_release_frees_the_project_for_the_next_driver(db_path):
    conn = connect_test_db(db_path)
    try:
        taken = _take(conn)
        coordination_claims.release(conn, taken.id, "release pair complete")
        retaken = _take(conn, SECOND)
        assert retaken.id != taken.id
        held = require_deploy_lock(
            conn, SLUG, session_id=SECOND, operation="deployment_runs.create"
        )
        assert held.id == retaken.id
    finally:
        conn.close()


def test_the_pipeline_refuses_to_execute_without_the_lock(capsys):
    """A run created under one hold is not resumed by a second driver."""
    from yoke_core.domain import deploy_pipeline

    def run_row(*args, sd=None):
        if args[:2] == ("runs", "get"):
            return "run-1|yoke|yoke-hosted-prod|prod||created|"
        return ""

    refusal = (
        "deployment run execution refused: no session holds the deploy lock "
        f"{deploy_lock_key(SLUG)} for project {SLUG!r}."
    )
    with (
        mock.patch.object(deploy_pipeline, "_yoke_db", side_effect=run_row),
        mock.patch.object(
            deploy_pipeline, "deploy_lock_refusal", return_value=refusal,
        ) as lock,
    ):
        rc = deploy_pipeline.run_pipeline("run-1", sd="/tmp/sd")

    assert rc == deploy_pipeline.EXIT_USAGE
    assert deploy_lock_key(SLUG) in capsys.readouterr().err
    assert lock.call_args.args[0] == SLUG
    assert lock.call_args.kwargs["operation"] == "deployment run execution"
