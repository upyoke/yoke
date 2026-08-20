"""Project install/refresh never reads a repository deployment-flow file.

Flows are control-plane rows created and retired by command. A file some
project repository still carries from an older Yoke — any schema, any
shape, even unparseable — belongs to that project now: install must
neither read it, validate it, fail on it, nor write to it. Such a file may
well have consumers of its own inside its repository; what ends is Yoke's
claim on it, not the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install import runner
from yoke_core.domain.project_install_test_helpers import make_bundle


DECLARATION = ".yoke/deployment-flows.json"

#: The shapes real project checkouts carry today, plus an unparseable one.
INERT_DECLARATIONS = {
    "schema_2": json.dumps({
        "schema": 2,
        "default_flow": "acme-release",
        "retire_if_present": ["acme-old"],
        "flows": [{
            "id": "acme-release",
            "name": "Acme release",
            "stages": [{"name": "merged", "step_runner": "auto"}],
            "target_env": "prod",
        }],
    }),
    "schema_3": json.dumps({
        "schema": 3,
        "flows": [{
            "id": "acme-prod",
            "name": "Acme prod",
            "stages": [{"name": "merged", "step_runner": "auto"}],
            "target_tier": "persistent",
            "target_environment_id": 4,
        }],
    }),
    "schema_4": json.dumps({
        "schema": 4,
        "default_flow": "acme-internal",
        "flows": [{
            "id": "acme-internal",
            "name": "Acme internal",
            "stages": [{"name": "merged", "step_runner": "auto"}],
        }],
    }),
    "malformed": '{"schema": 3, "flows": [',
}


@pytest.fixture
def install_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A checkout whose install reaches its own writers without a network."""
    repo = tmp_path / "repo"
    (repo / ".yoke").mkdir(parents=True)
    monkeypatch.setattr(
        runner.git_hooks_layer, "assert_pre_commit_runtime_available",
        lambda: None,
    )
    monkeypatch.setattr(
        runner, "_resolve_bundle",
        lambda *_args, **_kwargs: (make_bundle(), "test"),
    )
    monkeypatch.setattr(
        runner, "_register_in_machine_config",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        runner, "apply_bundle", lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        runner, "sync_local_snapshot_for_write",
        lambda **_kwargs: {"status": "skipped"},
    )
    return repo


@pytest.mark.parametrize("shape", sorted(INERT_DECLARATIONS))
def test_refresh_succeeds_and_leaves_any_flow_file_untouched(
    shape: str,
    install_repo: Path,
    tmp_path: Path,
) -> None:
    declaration = install_repo / DECLARATION
    declaration.write_text(INERT_DECLARATIONS[shape], encoding="utf-8")
    before = declaration.read_bytes()

    report = runner.refresh(
        install_repo,
        project_id=7,
        config_path=tmp_path / "machine-home" / "config.json",
    )

    assert "deployment_flows" not in report
    assert declaration.read_bytes() == before


def test_install_seeds_no_flow_file_into_a_fresh_checkout(
    install_repo: Path,
    tmp_path: Path,
) -> None:
    runner.install(
        install_repo,
        project_id=7,
        config_path=tmp_path / "machine-home" / "config.json",
    )

    assert not (install_repo / DECLARATION).exists()
