"""How the wizard fetches, shows, and records the checkout inspection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_reuse_feedback
from yoke_cli.config import onboard_wizard_flow_checkout_inspection as inspection
from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config import project_onboard_clone
from yoke_cli.config.onboard_wizard_checkout_inspection_screen import (
    LAYER_ROWS,
    inspection_body,
    inspection_lines,
)
from yoke_cli.config.project_onboard_support import ProjectOnboardError

from runtime.api.cli.onboard_checkout_inspection_fixtures import (
    clean_repo as _clean_repo,
    repo_with_layer as _repo_with_layer,
)


def _review_lines(summary: dict | None, decision: str) -> list[str]:
    plan = {
        "plan": {
            "reuse": {"project_installed_layer": summary},
            "project": {
                "checkout": "/code/buzz",
                "clone": {"existing_layer_decision": decision},
            },
        }
    }
    return onboard_reuse_feedback.grouped_lines_for_plan(plan)["repo"]


def test_review_describes_a_clean_checkout(tmp_path: Path) -> None:
    summary = layer.summarize(_clean_repo(tmp_path))

    lines = _review_lines(summary, "")

    assert any("No existing Yoke files" in line for line in lines)


def test_review_describes_the_layer_and_the_decision(tmp_path: Path) -> None:
    summary = layer.summarize(_repo_with_layer(tmp_path))

    removed = _review_lines(summary, layer.LAYER_DECISION_REMOVE)
    kept = _review_lines(summary, layer.LAYER_DECISION_KEEP)
    undecided = _review_lines(summary, "")

    assert any("Apply will remove it first" in line for line in removed)
    assert any("Apply will install over it" in line for line in kept)
    assert any("cannot run until you choose" in line for line in undecided)
    assert any("installed by Yoke 0.1.1" in line for line in removed)


def test_inspection_screen_names_every_group_and_both_choices(
    tmp_path: Path,
) -> None:
    scan = layer.scan(_repo_with_layer(tmp_path))

    lines = inspection_lines(scan)

    assert any(line.startswith(".yoke —") for line in lines)
    assert any("your own text stays" in line for line in lines)
    assert any("your other settings stay" in line for line in lines)
    assert {row.value for row in LAYER_ROWS} == set(layer.LAYER_DECISIONS)
    assert inspection_body(scan)


def test_inspection_lines_count_a_single_file_in_the_singular(
    tmp_path: Path,
) -> None:
    lines = inspection_lines(layer.scan(_repo_with_layer(tmp_path)))

    assert any(line.endswith("1 file, whole folder") for line in lines)


class _InspectionShell(inspection.CheckoutInspectionFlow):
    """A wizard shell that runs the checking worker inline."""

    def __init__(self, checkout: Path, remote: str) -> None:
        self.result = SimpleNamespace(
            config_path=str(checkout.parent / "config.json"),
            api_url="https://yoke.example",
            project_checkout=str(checkout),
            project_remote_url=remote,
            project_clone_existing_layer_decision="",
            existing_project_id=None,
            machine_github_api_url=None,
        )
        self.views: list = []
        self.outcome_visits = 0
        self.existing_project_visits = 0
        self.folder_visits = 0

    def _run_checking(self, *, work, on_success, on_error, **_kwargs) -> None:
        try:
            on_success(work())
        except Exception as exc:  # noqa: BLE001 - mirrors the worker's routing
            on_error(exc)

    def _goto(self, view) -> None:
        self.views.append(view)

    def _goto_clone_outcome(self) -> None:
        self.outcome_visits += 1

    def _after_existing_project_ready(self) -> None:
        self.existing_project_visits += 1

    def _goto_clone_folder(self) -> None:
        self.folder_visits += 1


def _stub_clone(monkeypatch, root: Path, builder) -> list[Path]:
    cloned: list[Path] = []

    def clone(target, remote_url, **_kwargs):
        cloned.append(Path(target))
        builder()
        return False

    monkeypatch.setattr(
        project_onboard_clone, "resumable_clone_with_machine_access", clone,
    )
    monkeypatch.setattr(inspection, "github_connected", lambda _result: False)
    return cloned


def test_wizard_fetches_the_repository_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "buzz"
    cloned = _stub_clone(monkeypatch, root, lambda: _repo_with_layer(tmp_path))
    shell = _InspectionShell(root, "https://github.com/acme/buzz.git")

    shell._materialize_and_inspect_checkout()

    assert cloned == [root]
    # The decision screen is shown; nothing has moved past it yet.
    assert len(shell.views) == 1
    assert shell.outcome_visits == 0


def test_wizard_records_the_removal_decision_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "buzz"
    _stub_clone(monkeypatch, root, lambda: _repo_with_layer(tmp_path))
    shell = _InspectionShell(root, "https://github.com/acme/buzz.git")
    shell._materialize_and_inspect_checkout()

    shell._on_checkout_inspection(layer.LAYER_DECISION_REMOVE)

    assert (
        shell.result.project_clone_existing_layer_decision
        == layer.LAYER_DECISION_REMOVE
    )
    assert shell.outcome_visits == 1


def test_wizard_continues_past_a_clean_repository_without_a_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "buzz"
    _stub_clone(monkeypatch, root, lambda: _clean_repo(tmp_path))
    shell = _InspectionShell(root, "https://github.com/acme/buzz.git")

    shell._materialize_and_inspect_checkout()

    # Nothing to keep or remove, so no screen and no decision to record.
    assert shell.views == []
    assert shell.result.project_clone_existing_layer_decision == ""
    assert shell.outcome_visits == 1


def test_wizard_offers_another_folder_when_the_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args, **_kwargs):
        raise ProjectOnboardError("remote refused the clone")

    monkeypatch.setattr(
        project_onboard_clone, "resumable_clone_with_machine_access", fail,
    )
    monkeypatch.setattr(inspection, "github_connected", lambda _result: False)
    shell = _InspectionShell(tmp_path / "buzz", "https://github.com/acme/buzz.git")

    shell._materialize_and_inspect_checkout()
    shell._on_checkout_fetch_error("choose-folder")

    assert shell.folder_visits == 1
    assert shell.outcome_visits == 0
