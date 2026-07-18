"""CLI contract for rendered artifact preview/apply/verify."""

from __future__ import annotations

from yoke_cli.commands.adapters import project_artifacts as adapter
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def _report(*, drift: bool, refused: bool = False) -> dict:
    return {
        "operation": "verify",
        "drift": drift,
        "refused": refused,
        "plan": {
            "creates": [],
            "updates": [],
            "prunes": [],
            "conflicts": [],
        },
    }


def test_registered_cli_surface_is_dedicated_from_substrate_refresh() -> None:
    function_id, handler = SUBCOMMAND_REGISTRY[("project", "artifacts", "refresh")]
    assert function_id == "project.artifacts.refresh"
    assert handler is adapter.project_artifacts_refresh
    assert SUBCOMMAND_REGISTRY[("project", "refresh")][0] == "project.refresh.run"


def test_verify_exits_nonzero_on_external_drift(monkeypatch, capsys) -> None:
    monkeypatch.setattr(adapter, "refresh", lambda *args, **kwargs: _report(drift=True))
    rc = adapter.project_artifacts_refresh(
        [
            "/tmp/sample-service",
            "--project",
            "sample-service",
            "--verify",
            "--json",
        ]
    )
    assert rc == 1
    assert '"drift": true' in capsys.readouterr().out


def test_verify_is_green_when_fresh_render_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter, "refresh", lambda *args, **kwargs: _report(drift=False)
    )
    assert (
        adapter.project_artifacts_refresh(
            [
                "/tmp/sample-service",
                "--project",
                "sample-service",
                "--verify",
            ]
        )
        == 0
    )


def test_adopt_existing_is_forwarded_as_distinct_operation(monkeypatch) -> None:
    received = {}

    def fake_refresh(*args, **kwargs):
        received.update(kwargs)
        return _report(drift=True)

    monkeypatch.setattr(adapter, "refresh", fake_refresh)
    assert (
        adapter.project_artifacts_refresh(
            [
                "/tmp/sample-service",
                "--project",
                "sample-service",
                "--adopt-existing",
            ]
        )
        == 0
    )
    assert received["adopt_existing"] is True
