"""Worktree validation provisioning output stays actionable."""

from __future__ import annotations

from yoke_core.domain import worktree_provision, worktree_validation_surface
from yoke_core.domain.yoke_connected_env import ConnectedEnvNotLocalPostgres


def _remote_control_plane_error() -> None:
    try:
        raise ConnectedEnvNotLocalPostgres("https has no local Postgres")
    except ConnectedEnvNotLocalPostgres as exc:
        raise RuntimeError(str(exc)) from exc


def test_remote_control_plane_skip_is_silent(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        worktree_validation_surface,
        "provision_validation_surfaces",
        lambda *_args: _remote_control_plane_error(),
    )

    worktree_provision.provision_worktree_validation_surfaces("/lane", "yoke")

    assert capsys.readouterr().err == ""


def test_local_provisioning_failure_remains_actionable(monkeypatch, capsys) -> None:
    def _raise(*_args):
        raise RuntimeError("recipe failed")

    monkeypatch.setattr(
        worktree_validation_surface, "provision_validation_surfaces", _raise,
    )

    worktree_provision.provision_worktree_validation_surfaces("/lane", "yoke")

    assert "recipe failed" in capsys.readouterr().err
