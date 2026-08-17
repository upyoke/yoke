"""Regression coverage for migration capability connection ownership."""

from __future__ import annotations

import pytest

from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_apply_resolve import _resolve_capability_settings
from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401
    _connect_validation_db,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401


def test_resolves_capability_from_supplied_control_connection(apply_env) -> None:
    control = _conn(apply_env["control_db"])
    try:
        capability = _resolve_capability_settings(control, "yoke")
    finally:
        control.close()
    assert capability["models"]["primary"]["runner"]["kind"] == (
        "governed_migration_module"
    )


def test_does_not_switch_to_an_ambient_control_plane(
    apply_env, monkeypatch
) -> None:
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("opened a second connection"),
    )
    control = _conn(apply_env["control_db"])
    try:
        capability = _resolve_capability_settings(control, "yoke")
    finally:
        control.close()
    assert "models" in capability


def test_validation_connection_is_rejected_instead_of_falling_back(
    apply_env,
) -> None:
    validation = _connect_validation_db(apply_env)
    try:
        with pytest.raises(MigrationApplyError, match="supplied control-plane"):
            _resolve_capability_settings(validation, "yoke")
    finally:
        validation.close()


def test_unknown_project_raises_typed_error(apply_env) -> None:
    control = _conn(apply_env["control_db"])
    try:
        with pytest.raises(MigrationApplyError, match="no migration_model"):
            _resolve_capability_settings(control, "no-such-project")
    finally:
        control.close()


def test_empty_settings_raise_typed_error(apply_env) -> None:
    control = _conn(apply_env["control_db"])
    try:
        control.execute(
            "UPDATE project_capabilities SET settings = '{}' "
            "WHERE project_id = %s AND type = %s",
            (1, "migration_model"),
        )
        control.commit()
        with pytest.raises(MigrationApplyError, match="empty or malformed"):
            _resolve_capability_settings(control, "yoke")
    finally:
        control.close()
