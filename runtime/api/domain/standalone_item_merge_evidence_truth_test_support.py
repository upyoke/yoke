# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.dash_posture_deployment_containment_test_support import _git as _git

from runtime.api.domain.standalone_merge_simulation_support import integrate_candidate

import json as json

import subprocess

from pathlib import Path as Path

from types import SimpleNamespace

import pytest as pytest

from runtime.api.domain.standalone_merge_simulation_support import (
    stub_candidate_review,
)

from yoke_core.domain import standalone_item_merge as sim

from yoke_core.domain import standalone_item_merge_cli as sim_cli

from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)

from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

from yoke_core.domain import standalone_item_merge_evidence as evidence

from yoke_core.domain import standalone_item_merge_git as merge_git

from yoke_core.domain import item_merge_receipts as receipts

from yoke_core.domain import standalone_item_merge_terminal as terminal

from yoke_core.domain.standalone_item_merge_landed import LandedLane

from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates


@pytest.fixture(autouse=True)
def _no_candidate_review(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_candidate_review(monkeypatch)


MERGE_SHA = "b" * 40


@pytest.fixture(autouse=True)
def _receipt_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-m", "base")
    _git(root, "checkout", "-b", "ITEM-1")
    (root / "feature.txt").write_text("feature\n")
    _git(root, "add", "feature.txt")
    _git(root, "commit", "-m", "feature")
    _git(root, "checkout", "main")
    return root


def _item(repo: Path, *, status: str = "reviewing-implementation") -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": status,
        "workflow": {"id": "dash"},
        "worktrees": [
            {"branch": "ITEM-1", "commit_sha": _git(repo, "rev-parse", "ITEM-1")}
        ],
    }


def _section_response(content: str | None):
    """A stand-in for ``items.section.get`` over the evidence section."""
    if content is None:
        return SimpleNamespace(
            success=True,
            error=None,
            result={"section_name": DASH_EVIDENCE_SECTION, "found": False},
        )
    return SimpleNamespace(
        success=True,
        error=None,
        result={
            "section_name": DASH_EVIDENCE_SECTION,
            "found": True,
            "content": content,
        },
    )


def _evidence_content(merge_sha: str = MERGE_SHA) -> str:
    return json.dumps(
        {
            "schema": 1,
            "result_summary": "landed",
            "verification_summary": "suite green",
            "verification_status": "passed",
            "commit_sha": "a" * 40,
            "merge_sha": merge_sha,
            "touched_files": ["feature.txt"],
            "recorded_at": "2026-01-01T00:00:00Z",
        }
    )


def _wire_merge(monkeypatch: pytest.MonkeyPatch, repo: Path, item: dict) -> None:
    monkeypatch.setattr(sim_cli, "_resolve_item", lambda ref, project: (item, ""))
    monkeypatch.setattr(
        sim_cli,
        "_resolve_checkout",
        lambda _item, target: (repo, "main"),
    )
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
    monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
    monkeypatch.setattr(sim, "_run_merge_engine", integrate_candidate)
