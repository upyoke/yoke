"""Whatever onboarding already finds is the headline, before any choice.

A checkout that already carries a Yoke layer, a repository that already has a
project, and a checkout already mapped on this machine are all discoveries the
operator should read before answering anything — and connecting to what exists
is the answer already under the cursor. Replacing it stays available, one row
down, because it is the rare answer rather than the safe one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_existing_project
from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config.onboard_wizard_checkout_inspection_screen import (
    LAYER_ROWS,
    inspection_body,
)
from yoke_cli.config.onboard_wizard_existing_project_detected import (
    CHOICE_CONNECT,
    CHOICE_NEW_PROJECT,
    DETECTED_ROWS,
    ExistingProjectDetectedFlow,
)
from yoke_cli.config.onboard_wizard_stored_project import StoredProjectFlow
from yoke_cli.config.onboard_wizard_widgets import SelectionList

from runtime.api.cli.onboard_checkout_inspection_fixtures import (
    repo_with_layer as _repo_with_layer,
)


def _first_row_value(rows) -> str:
    return rows[0].value


def _title_of(widgets) -> str:
    return str(widgets[0].render())


def test_an_existing_layer_is_announced_and_kept_by_default(tmp_path: Path) -> None:
    scan = layer.scan(_repo_with_layer(tmp_path))

    widgets = inspection_body(scan)

    assert "already has Yoke files" in _title_of(widgets)
    # The headline is a finding, not a failure: the error styling would read
    # as something having gone wrong with the repository.
    assert "✗" not in _title_of(widgets)
    assert _first_row_value(LAYER_ROWS) == layer.LAYER_DECISION_KEEP


def test_an_existing_project_is_announced_and_connected_by_default() -> None:
    assert _first_row_value(DETECTED_ROWS) == CHOICE_CONNECT
    assert {row.value for row in DETECTED_ROWS} == {
        CHOICE_CONNECT,
        CHOICE_NEW_PROJECT,
    }


class _DetectionShell(ExistingProjectDetectedFlow):
    """The routing surface the detection screen's two answers reach."""

    def __init__(self) -> None:
        self.result = SimpleNamespace(
            existing_project_id=7,
            existing_project_match_source="github_repo",
            existing_project_local_source=None,
            project_slug="buzz",
            project_name="Buzz",
            project_default_branch="main",
            project_public_item_prefix="BZZ",
            project_github_adoption="app_binding",
            project_github_adoption_preserve=True,
        )
        self.announced: list[object] = []
        self.continued = 0
        self.slug_prompts = 0
        self.folder_prompts = 0

    def _goto_existing_project_ready(self, *, on_choice=None) -> None:
        self.announced.append(on_choice)

    def _after_existing_project_ready(self) -> None:
        self.continued += 1

    def _goto_slug(self) -> None:
        self.slug_prompts += 1

    def _goto_clone_folder(self) -> None:
        self.folder_prompts += 1


def test_the_clone_path_announces_the_match_before_the_folder() -> None:
    shell = _DetectionShell()

    shell._goto_clone_existing_project_detected()

    assert shell.announced, "the match must be announced before anything else"
    assert shell.folder_prompts == 0

    shell._on_clone_existing_project_detected(CHOICE_CONNECT)

    assert shell.result.existing_project_id == 7
    assert shell.folder_prompts == 1


def test_declining_the_match_sets_up_a_separate_project() -> None:
    shell = _DetectionShell()

    shell._on_clone_existing_project_detected(CHOICE_NEW_PROJECT)

    assert shell.result.existing_project_id is None
    assert shell.result.project_slug is None
    assert shell.folder_prompts == 1


def test_a_local_checkout_match_connects_or_names_a_new_project() -> None:
    connected = _DetectionShell()
    connected._on_existing_project_detected(CHOICE_CONNECT)

    declined = _DetectionShell()
    declined._on_existing_project_detected(CHOICE_NEW_PROJECT)

    assert connected.continued == 1
    assert declined.slug_prompts == 1
    assert declined.result.existing_project_id is None


def test_clear_match_keeps_the_repository_the_operator_chose() -> None:
    result = SimpleNamespace(
        existing_project_id=7,
        existing_project_match_source="github_repo",
        existing_project_local_source=None,
        project_slug="buzz",
        project_name="Buzz",
        project_default_branch="main",
        project_public_item_prefix="BZZ",
        project_github_adoption="app_binding",
        project_github_adoption_preserve=True,
        project_github_repo="octo/buzz",
        project_checkout="/code/buzz",
    )

    onboard_existing_project.clear_match(result)

    assert result.project_github_repo == "octo/buzz"
    assert result.project_checkout == "/code/buzz"


class _StoredProjectShell(StoredProjectFlow):
    def __init__(self, checkouts) -> None:
        self._stored_project_checkouts = checkouts
        self.views: list[tuple] = []

    def _goto(self, view) -> None:
        self.views.append(view)

    def _selection_view(self, step, title, subtitle, rows, on_select):
        return (step, title, subtitle, rows, on_select)


def test_a_mapped_checkout_is_announced_and_reused_by_default(
    tmp_path: Path,
) -> None:
    shell = _StoredProjectShell(
        [
            machine_config.ConfiguredProject(
                checkout=tmp_path, project_id=4, entry={},
            )
        ]
    )

    shell._goto_stored_project_picker()

    _step, title, _subtitle, rows, _on_select = shell.views[0]
    assert title.startswith("1 Yoke project already set up")
    assert rows[0].value == "stored:0"
    assert rows[0].label == str(tmp_path)


def test_the_detection_rows_are_a_selectable_list() -> None:
    # The rows reach a real SelectionList, so the first one is what Enter takes.
    assert SelectionList(DETECTED_ROWS).selected_value == CHOICE_CONNECT
