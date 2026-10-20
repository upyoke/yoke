"""Back and Forward through the clone folder never asks to resume this run's own clone."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import fake_clone
from yoke_cli.config import onboard_wizard_flow_checkout_inspection as inspection
from yoke_cli.config import project_onboard_clone
from yoke_cli.config.onboard_wizard import WizardResult
from yoke_cli.config.onboard_wizard_flow_clone import CloneFlow
from yoke_cli.config.setup_run_facts import RunFacts

pytest.importorskip("textual")

REMOTE = "https://github.com/acme/demo.git"


class _Shell(CloneFlow):
    """The wizard's clone steps with checks run inline and screens recorded."""

    def __init__(self, config: Path) -> None:
        self.result = WizardResult(
            config_path=str(config),
            env_name="local",
            api_url="",
            project_remote_url=REMOTE,
        )
        self._run_facts = RunFacts()
        self.keys: list[str] = []

    def _run_checking(self, *, work, on_success, on_error, **_kwargs) -> None:
        try:
            value = work()
        except Exception as exc:  # noqa: BLE001 - mirrors the worker's routing
            on_error(exc)
            return
        on_success(value)

    def _goto(self, view) -> None:
        self.keys.append(view.prompt.key)


@pytest.fixture
def shell(tmp_path: Path, monkeypatch) -> _Shell:
    monkeypatch.setattr(
        project_onboard_clone, "clone_with_connected_access", fake_clone
    )
    monkeypatch.setattr(inspection, "github_connected", lambda _result: False)
    return _Shell(tmp_path / "config.json")


def test_returning_to_the_folder_this_run_cloned_shows_its_layer_again(
    shell, tmp_path: Path
):
    folder = str(tmp_path / "code" / "demo")
    shell._after_clone_folder(folder)
    assert shell.keys == ["project.checkout_layer"]

    # Back to the folder screen, then the same folder again.
    shell._after_clone_folder(folder)

    assert shell.keys == ["project.checkout_layer", "project.checkout_layer"]


def test_a_clone_this_run_did_not_make_still_offers_resume(shell, tmp_path: Path):
    folder = tmp_path / "code" / "demo"
    fake_clone(folder.parent, folder.name, REMOTE)

    shell._after_clone_folder(str(folder))

    assert shell.keys == ["project.clone_resume"]
