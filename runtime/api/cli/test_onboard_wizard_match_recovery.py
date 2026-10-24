"""Back navigation restores the project matched by that detection view."""

import pytest

from runtime.api.cli.test_onboard_wizard_existing_detection_first import _DetectionShell
from yoke_cli.config.onboard_wizard_existing_project_detected import (
    CHOICE_CONNECT, CHOICE_DETAILS, CHOICE_NEW_PROJECT, ExistingProjectDetectedFlow,
)


class DetectionHistory(_DetectionShell):
    def __init__(self):
        super().__init__()
        self.result.env_name = "prod"
        self.result.destination = "hosted"
        self.result.project_mode = "local"
        self.result.project_github_repo = "octo/buzz"
        self.result.project_checkout_origin_url = "https://github.com/octo/buzz.git"
        self.result.project_checkout = "/code/buzz"
        self.views = []

    _goto_existing_project_ready = ExistingProjectDetectedFlow._goto_existing_project_ready

    def _goto(self, view):
        self.views.append(view)

    def _replace_current(self, view):
        self.views[-1] = view


@pytest.mark.parametrize("clone", [False, True])
@pytest.mark.parametrize("details", [False, True])
def test_back_from_separate_project_restores_full_matched_identity(clone, details):
    shell = DetectionHistory()
    expected = vars(shell.result).copy()
    if clone:
        shell._goto_clone_existing_project_detected()
    else:
        shell._goto_existing_project_ready()
    detected = shell.views[-1]

    detected.on_select(CHOICE_NEW_PROJECT)
    assert shell.result.existing_project_id is None
    assert shell.result.project_slug is None
    assert shell.result.project_github_adoption_preserve is False

    # The shell's history restores this exact view on Esc, without rolling
    # back unrelated answers or checkout state.
    if details:
        detected.on_select(CHOICE_DETAILS)
        detected = shell.views[-1]
        assert "Project: buzz" in detected.prompt.detail_lines
    detected.on_select(CHOICE_CONNECT)

    assert vars(shell.result) == expected
    assert shell.folder_prompts == (2 if clone else 0)
    assert shell.continued == (0 if clone else 1)


def test_older_detection_view_keeps_its_own_match_and_routing():
    shell = DetectionHistory()
    shell._goto_existing_project_ready()
    original = shell.views[-1]
    original.on_select(CHOICE_NEW_PROJECT)
    shell.result.existing_project_id = 9
    shell.result.project_slug = "another"
    shell._goto_clone_existing_project_detected()

    original.on_select(CHOICE_CONNECT)

    assert shell.result.existing_project_id == 7
    assert shell.result.project_slug == "buzz"
    assert shell.continued == 1
    assert shell.folder_prompts == 0
