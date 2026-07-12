"""Test seam for local bare repositories below the GitHub trust boundary."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import project_clone_support, project_onboard_clone


def allow_local_clone(monkeypatch: Any) -> None:
    def passthrough(remote_url: str, **_kwargs: Any) -> str:
        return remote_url

    monkeypatch.setattr(project_onboard_clone, "clean_remote_url", passthrough)
    monkeypatch.setattr(project_clone_support, "clean_remote_url", passthrough)
    monkeypatch.setattr(
        project_clone_support,
        "isolated_remote_config",
        lambda *args, **kwargs: ("core.askPass=",),
    )


__all__ = ["allow_local_clone"]
