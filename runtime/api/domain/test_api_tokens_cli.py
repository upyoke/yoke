"""API-token operator CLI coverage."""

from __future__ import annotations

import stat

import pytest

from yoke_core.domain import api_tokens_cli, json_helper
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import TOKEN_PREFIX, verify_token
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


@pytest.fixture()
def tokendb(test_db):
    conn = test_db
    seed_project_identities(conn)
    seed_roles_and_permissions(conn)
    conn.commit()
    return conn


def test_bootstrap_admin_outputs_raw_token_once_and_stores_only_hash(tokendb, capsys):
    rc = api_tokens_cli.main(
        ["bootstrap-admin", "--actor-label", "ops-lead", "--project", "yoke"]
    )
    assert rc == 0
    body = json_helper.loads_text(capsys.readouterr().out)
    assert body["raw_token"].startswith(TOKEN_PREFIX)

    verified = verify_token(tokendb, body["raw_token"])
    assert verified.actor_id == body["actor_id"]
    project_id = resolve_project_id(tokendb, "yoke")
    row = tokendb.execute(
        "SELECT 1 FROM actor_project_roles WHERE actor_id = %s AND project_id = %s",
        (body["actor_id"], project_id),
    ).fetchone()
    assert row is not None
    raw_stored = tokendb.execute(
        "SELECT 1 FROM api_tokens WHERE token_hash = %s",
        (body["raw_token"],),
    ).fetchone()
    assert raw_stored is None


def test_bootstrap_admin_defaults_to_neutral_label_and_org_admin(tokendb, capsys):
    """No flags: the admin label is neutral and the grant is the org admin role."""
    from yoke_core.domain.actors import resolve_actor_by_label
    from yoke_core.domain.api_tokens import DEFAULT_ADMIN_ACTOR_LABEL

    rc = api_tokens_cli.main(["bootstrap-admin"])
    assert rc == 0
    body = json_helper.loads_text(capsys.readouterr().out)
    assert (
        resolve_actor_by_label(tokendb, DEFAULT_ADMIN_ACTOR_LABEL) == body["actor_id"]
    )
    row = tokendb.execute(
        "SELECT 1 FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND r.name = 'admin'",
        (body["actor_id"],),
    ).fetchone()
    assert row is not None


def test_mint_and_revoke(tokendb, capsys):
    actor_id = seed_human_actor(tokendb)
    rc = api_tokens_cli.main(
        ["mint", "--actor", str(actor_id), "--name", "dev-machine"]
    )
    assert rc == 0
    body = json_helper.loads_text(capsys.readouterr().out)
    verify_token(tokendb, body["raw_token"])

    assert api_tokens_cli.main(["revoke", "--token-id", str(body["token_id"])]) == 0
    with pytest.raises(Exception):
        verify_token(tokendb, body["raw_token"])


def test_mint_unknown_actor_errors(tokendb):
    rc = api_tokens_cli.main(["mint", "--actor", "9999", "--name", "ghost"])
    assert rc == 1


def _service_args(*, role="infrastructure_ci", raw_token_file=None):
    args = [
        "bootstrap-project-service",
        "--system-component",
        "platform-infrastructure-ci",
        "--project",
        "yoke",
        "--role",
        role,
        "--name",
        "platform-infrastructure-ci",
    ]
    if raw_token_file is not None:
        args.extend(("--raw-token-file", str(raw_token_file)))
    return args


def test_bootstrap_project_service_grants_role_and_returns_token_once(
    tokendb,
    capsys,
):
    assert api_tokens_cli.main(_service_args()) == 0
    body = json_helper.loads_text(capsys.readouterr().out)
    raw_token = body["raw_token"]
    verified = verify_token(tokendb, raw_token)
    assert verified.actor_id == body["actor_id"]

    row = tokendb.execute(
        "SELECT a.kind, a.system_component, r.name, apr.granted_by_actor_id "
        "FROM actors a "
        "JOIN actor_project_roles apr ON apr.actor_id = a.id "
        "JOIN roles r ON r.id = apr.role_id "
        "WHERE a.id = %s",
        (body["actor_id"],),
    ).fetchone()
    assert tuple(row) == (
        "system",
        "platform-infrastructure-ci",
        "infrastructure_ci",
        None,
    )


def test_raw_token_file_mode_reuses_actor_and_grant_but_mints_fresh_token(
    tokendb,
    capsys,
    tmp_path,
):
    token_file = tmp_path / "platform-infrastructure-ci.token"
    assert api_tokens_cli.main(_service_args(raw_token_file=token_file)) == 0
    first = json_helper.loads_text(capsys.readouterr().out)
    first_raw = token_file.read_text(encoding="utf-8").strip()
    assert "raw_token" not in first
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    assert api_tokens_cli.main(_service_args(raw_token_file=token_file)) == 0
    second = json_helper.loads_text(capsys.readouterr().out)
    second_raw = token_file.read_text(encoding="utf-8").strip()
    assert "raw_token" not in second
    assert second["actor_id"] == first["actor_id"]
    assert second["token_id"] != first["token_id"]
    assert second_raw != first_raw
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert verify_token(tokendb, first_raw).actor_id == first["actor_id"]
    assert verify_token(tokendb, second_raw).actor_id == first["actor_id"]

    grant_count = tokendb.execute(
        "SELECT COUNT(*) FROM actor_project_roles WHERE actor_id = %s",
        (first["actor_id"],),
    ).fetchone()[0]
    assert grant_count == 1


def test_bootstrap_project_service_rejects_org_role_without_mutation(
    tokendb,
    capsys,
):
    assert api_tokens_cli.main(_service_args(role="admin")) == 1
    assert "not a project-scoped role" in capsys.readouterr().err
    actor = tokendb.execute(
        "SELECT 1 FROM actors WHERE system_component = %s",
        ("platform-infrastructure-ci",),
    ).fetchone()
    token = tokendb.execute(
        "SELECT 1 FROM api_tokens WHERE name = %s",
        ("platform-infrastructure-ci",),
    ).fetchone()
    assert actor is None
    assert token is None


def test_bootstrap_project_service_rejects_unknown_project_before_actor_creation(
    tokendb,
    capsys,
):
    args = _service_args()
    args[args.index("yoke")] = "missing-project"
    assert api_tokens_cli.main(args) == 1
    assert "not found" in capsys.readouterr().err
    actor = tokendb.execute(
        "SELECT 1 FROM actors WHERE system_component = %s",
        ("platform-infrastructure-ci",),
    ).fetchone()
    assert actor is None


def test_raw_token_file_refuses_symlink_before_mutation(
    tokendb,
    capsys,
    tmp_path,
):
    target = tmp_path / "existing-token"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "service-token"
    link.symlink_to(target)

    assert api_tokens_cli.main(_service_args(raw_token_file=link)) == 1
    assert "must not be a symlink" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "keep\n"
    actor = tokendb.execute(
        "SELECT 1 FROM actors WHERE system_component = %s",
        ("platform-infrastructure-ci",),
    ).fetchone()
    assert actor is None


def test_raw_token_file_write_failure_revokes_minted_token(
    tokendb,
    capsys,
    tmp_path,
    monkeypatch,
):
    def _fail_write(*_args, **_kwargs):
        raise ValueError("simulated protected-file failure")

    monkeypatch.setattr(api_tokens_cli, "_write_raw_token_file", _fail_write)
    token_file = tmp_path / "service-token"
    assert api_tokens_cli.main(_service_args(raw_token_file=token_file)) == 1
    assert "protected-file failure" in capsys.readouterr().err
    (token_status,) = tokendb.execute(
        "SELECT status FROM api_tokens WHERE name = %s",
        ("platform-infrastructure-ci",),
    ).fetchone()
    assert token_status == "revoked"
    assert not token_file.exists()
