"""Fail-closed service-token scope and protected-file rotation coverage."""

from __future__ import annotations

import stat

import pytest

from yoke_core.domain import api_tokens_cli, json_helper
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.api_tokens import verify_token
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


@pytest.fixture()
def tokendb(test_db):
    seed_project_identities(test_db)
    seed_roles_and_permissions(test_db)
    test_db.commit()
    return test_db


def _service_args(
    *,
    project: str = "yoke",
    role: str = "infrastructure_ci",
    raw_token_file=None,
) -> list[str]:
    args = [
        "bootstrap-project-service",
        "--system-component",
        "platform-infrastructure-ci",
        "--project",
        project,
        "--role",
        role,
        "--name",
        "platform-infrastructure-ci",
    ]
    if raw_token_file is not None:
        args.extend(("--raw-token-file", str(raw_token_file)))
    return args


@pytest.mark.parametrize(
    ("colliding_project", "colliding_role"),
    (
        pytest.param("yoke", "deployment_ci", id="different-role"),
        pytest.param("buzz", "infrastructure_ci", id="different-project"),
    ),
)
def test_reused_component_refuses_different_project_authority(
    tokendb,
    capsys,
    colliding_project,
    colliding_role,
):
    assert api_tokens_cli.main(_service_args()) == 0
    first = json_helper.loads_text(capsys.readouterr().out)

    assert (
        api_tokens_cli.main(
            _service_args(project=colliding_project, role=colliding_role)
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "different or broader authority" in captured.err
    assert "distinct component name" in captured.err
    assert verify_token(tokendb, first["raw_token"]).actor_id == first["actor_id"]

    grants = tokendb.execute(
        "SELECT p.slug, r.name FROM actor_project_roles apr "
        "JOIN projects p ON p.id = apr.project_id "
        "JOIN roles r ON r.id = apr.role_id "
        "WHERE apr.actor_id = %s",
        (first["actor_id"],),
    ).fetchall()
    assert [tuple(row) for row in grants] == [("yoke", "infrastructure_ci")]
    (token_count,) = tokendb.execute(
        "SELECT COUNT(*) FROM api_tokens WHERE actor_id = %s",
        (first["actor_id"],),
    ).fetchone()
    assert token_count == 1


def test_reused_component_refuses_org_authority(tokendb, capsys):
    assert api_tokens_cli.main(_service_args()) == 0
    first = json_helper.loads_text(capsys.readouterr().out)
    grant_actor_org_role(
        tokendb,
        actor_id=first["actor_id"],
        org_id=seed_default_org(tokendb),
        role_name=ROLE_ADMIN,
    )

    assert api_tokens_cli.main(_service_args()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "different or broader authority" in captured.err
    (token_count,) = tokendb.execute(
        "SELECT COUNT(*) FROM api_tokens WHERE actor_id = %s",
        (first["actor_id"],),
    ).fetchone()
    assert token_count == 1


def test_post_replace_directory_sync_failure_keeps_stored_token_active(
    tokendb,
    capsys,
    tmp_path,
    monkeypatch,
):
    token_file = tmp_path / "platform-infrastructure-ci.token"
    real_fsync = api_tokens_cli.os.fsync

    def fail_directory_sync(descriptor):
        if stat.S_ISDIR(api_tokens_cli.os.fstat(descriptor).st_mode):
            raise OSError("simulated directory fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(api_tokens_cli.os, "fsync", fail_directory_sync)

    assert api_tokens_cli.main(_service_args(raw_token_file=token_file)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "raw token file was replaced" in captured.err
    assert "token remains active in that file" in captured.err
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    raw_token = token_file.read_text(encoding="utf-8").strip()
    verified = verify_token(tokendb, raw_token)
    (status,) = tokendb.execute(
        "SELECT status FROM api_tokens WHERE id = %s",
        (verified.token_id,),
    ).fetchone()
    assert status == "active"
