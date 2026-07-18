"""Checkout nonmutation when project flow configuration is malformed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install import runner
from yoke_cli.project_install import deployment_flows as flow_layer
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain.project_install_test_helpers import make_bundle


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_malformed_declaration_fails_before_checkout_or_config_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    declaration = repo / ".yoke" / "deployment-flows.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_text('{"schema": 1, "flows": [', encoding="utf-8")
    (repo / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
    config = tmp_path / "machine-home" / "config.json"
    before = _snapshot(repo)
    monkeypatch.setattr(
        runner,
        "_resolve_bundle",
        lambda *_args, **_kwargs: (make_bundle(), "test"),
    )

    with pytest.raises(ProjectInstallError, match="invalid JSON"):
        runner.install(repo, project_id=7, config_path=config)

    assert _snapshot(repo) == before
    assert not config.exists()
    assert not (repo / ".yoke" / "install-manifest.json").exists()


def test_server_rejection_fails_before_checkout_or_config_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    declaration = repo / ".yoke" / "deployment-flows.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(json.dumps({
        "schema": 1,
        "flows": [{
            "id": "acme-production",
            "name": "Production",
            "stages": [{"name": "invalid"}],
        }],
    }), encoding="utf-8")
    (repo / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
    config = tmp_path / "machine-home" / "config.json"
    before = _snapshot(repo)
    monkeypatch.setattr(
        runner,
        "_resolve_bundle",
        lambda *_args, **_kwargs: (make_bundle(), "test"),
    )
    monkeypatch.setattr(
        flow_layer,
        "dispatch_declaration",
        lambda **_kwargs: FunctionCallResponse(
            success=False,
            function="deployment_flows.reconcile_project",
            version="v1",
            error=FunctionError(
                code="declaration_invalid",
                message="stage executor is required",
            ),
        ),
    )

    with pytest.raises(ProjectInstallError, match="stage executor is required"):
        runner.install(repo, project_id=7, config_path=config)

    assert _snapshot(repo) == before
    assert not config.exists()
    assert not (repo / ".yoke" / "install-manifest.json").exists()
