"""Shared fixtures for the release fleet rehearsal dispatch tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import deploy_pipeline_step_runners
from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain.migration_model_fleet_read import DeclaredFleets

_DIGEST = "a" * 64
RELEASE_CHECKOUT = Path("/release-checkout")
_RELEASE_SHA = "b" * 40
_HISTORY = ("0001_first_entry", "0002_rewrite_rows")
_RUN = "20260101T000000Z"
_MODULES_DIR = "packages/yoke-core/src/yoke_core/domain/migrations"


def _model(fleet: dict | None) -> dict:
    model: dict = {"runner": {"config": {"modules_dir": _MODULES_DIR}}}
    if fleet is not None:
        model["fleet"] = fleet
    return model


_ENGINE = _model({"kind": "engine_tenants"})


def _declare(monkeypatch, models: dict) -> None:
    """Declare each model, and its fleet when the test model carries one."""
    declared = DeclaredFleets(
        models={
            name: {k: v for k, v in model.items() if k != "fleet"}
            for name, model in models.items()
        },
        fleets={
            name: model["fleet"] for name, model in models.items() if "fleet" in model
        },
    )
    monkeypatch.setattr(rehearsal, "read_declared", lambda _project: (declared, ""))


def _stage(*, workflow: str = "platform-release-bridge.yml") -> dict:
    name = "hosted-release"
    config = {
        "name": name,
        "step_runner": "github-actions-workflow",
        "workflow": workflow,
    }
    return {"name": name, "step_runner": "github-actions-workflow", "config": config}


def _dispatch(
    stage: dict, environment: str = "prod", project: str = "yoke"
) -> tuple[int, str]:
    return deploy_pipeline_step_runners._dispatch_step_runner(
        stage,
        run_id="run-1",
        member_items=["1"],
        github_repo="upyoke/yoke",
        project=project,
        project_repo_path="/repo",
        branch="main",
        first_item="1",
        timeout_min=1,
        fresh=False,
        environment_name=environment,
        gate_branch="main",
        release_lineage=_RELEASE_SHA,
        sd=None,
    )


def _covered(
    *, entries: tuple[str, ...] = _HISTORY, shape: bool = True, model: str = "primary"
) -> dict:
    """The coverage leaves a passing rehearsal of this release leaves behind."""
    values = {receipt.entry_coverage_path(model, name): _RUN for name in entries}
    if shape:
        values[receipt.schema_shape_coverage_path(model, _DIGEST)] = _RUN
    return values


def _stable_commit(monkeypatch) -> None:
    """Everything a release commit contributes except its history entries."""
    monkeypatch.setattr(
        rehearsal,
        "_release_sha",
        lambda _lineage, _repository: (_RELEASE_SHA, ""),
    )
    monkeypatch.setattr(
        rehearsal.fleets,
        "schema_shape_digest_at",
        lambda _fleet, _repository, _sha: _DIGEST,
    )
    monkeypatch.setattr(
        rehearsal.deploy_pipeline_environment,
        "release_control_plane_env",
        lambda: "prod",
    )
    monkeypatch.setattr(
        rehearsal.release_source, "engine_source_mismatch", lambda *_a: ""
    )
    monkeypatch.setattr(rehearsal.release_source, "release_checkout", _release_checkout)


@contextmanager
def _release_checkout(_repository: str, _sha: str) -> Iterator[Path]:
    yield RELEASE_CHECKOUT


def _stable_release(monkeypatch, models: dict | None = None) -> None:
    _stable_commit(monkeypatch)
    _declare(monkeypatch, {"primary": _ENGINE} if models is None else models)
    monkeypatch.setattr(
        rehearsal,
        "_release_history",
        lambda _repository, _sha, _modules_dir: (_HISTORY, ""),
    )
