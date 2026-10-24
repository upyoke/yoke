"""Explicit CLI destinations survive adoption and separate-project routing."""

import subprocess

import pytest

from yoke_cli.commands.adapters import onboard, onboard_interactive
from yoke_cli.config import existing_project_lookup, github_publish, machine_config
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_wizard_existing_project_detected import CHOICE_NEW_PROJECT
from yoke_cli.config.onboard_wizard_flows import SETUP_FLOWS, init_setup_state


class FlowShell(*SETUP_FLOWS):
    """Run the native and agent shells' shared graph with offline transport."""

    def _hydrate_stored_credentials(self, defaults):
        pass

    def _goto(self, view):
        self.view = view

    def _run_checking(self, *, work, on_success, **kwargs):
        on_success(work())

    def _goto_input(self, key, *args, on_done, **kwargs):
        self.input_key, self.input_done = key, on_done

    def _fetch_repo_owners(self):
        return [github_publish.RepoOwner("owned", "user")]

    def _after_prefix(self, value):
        self.review = self.result.build_report_kwargs(apply=False, check_identity=False)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def adopted(tmp_path, monkeypatch):
    root = tmp_path / "adopted"
    root.mkdir()
    git(root, "init", "-b", "main")
    source = "https://github.com/source/widgets.git"
    git(root, "remote", "add", "origin", source)
    monkeypatch.setattr(existing_project_lookup, "find_local_project_reference", lambda *a, **k: None)
    monkeypatch.setattr(
        existing_project_lookup, "find_by_github_repo",
        lambda **k: existing_project_lookup.ExistingProject(
            7, "widgets", "Widgets", "source/widgets", "main", "WIDG"
        ),
    )
    monkeypatch.setattr(machine_config, "github_config", lambda *a: {})
    return root, source


def shell_for(root, outcome):
    parsed = onboard._parser().parse_args([
        "--project-mode", "local-checkout", "--checkout", str(root),
        "--publication-destination", outcome,
    ])
    defaults = onboard_interactive.wizard_defaults(parsed, "test", "quick", "hosted")
    assert defaults.project_clone_outcome == outcome
    shell = FlowShell()
    init_setup_state(shell, defaults=defaults, apply_report=lambda **k: {})
    shell.result.api_url = "https://test.invalid"
    shell.result.token = "fixture-only"
    shell.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
    shell.result.machine_github_verification = {"ready": True, "ok": True}
    shell._after_checkout(str(root))
    assert shell.view.prompt.key == "project.existing_found"
    assert shell.result.project_clone_outcome is None  # reset does not consume the preset
    shell.view.on_select(CHOICE_NEW_PROJECT)
    return shell


def test_adopted_separate_duplicate_collects_target_before_review(adopted):
    root, source = adopted
    shell = shell_for(root, "make-it-mine")
    assert shell.view.prompt.key == "project.new_repo_visibility"
    shell.view.on_select("private")
    shell.view.on_form({"slug": "copy", "name": "Copy", "branch": "main", "prefix": "COPY"})
    assert shell.view.prompt.key == "project.publish_owner"
    shell.view.on_select("owned")
    assert shell.input_key == "project.publish_repo_name"
    shell.input_done("duplicate")

    review = shell.review
    plan = review["project_clone"]
    assert plan.outcome == "make-it-mine"
    assert plan.publish.owner == "owned"
    assert plan.publish.name == "duplicate"
    assert plan.publish.private is True
    assert review["project_github_repo"] == "owned/duplicate"
    assert review["project_remote_url"] == source
    assert review["project_keep_existing_remote"] is False
    assert review["project_publish"] is None  # duplicate creation belongs to the clone plan
    applied = shell.result.build_report_kwargs(apply=True, check_identity=True)
    assert applied["project_clone"] == plan
    assert applied["project_github_repo"] == "owned/duplicate"
    assert git(root, "remote", "get-url", "origin") == source


@pytest.mark.parametrize("outcome", ["source", "just-clone", "fork"])
def test_adopted_separate_preserves_other_explicit_destinations(adopted, outcome):
    root, source = adopted
    shell = shell_for(root, outcome)
    assert shell.result.project_clone_outcome == outcome
    shell.view.on_form({"slug": "copy", "name": "Copy", "branch": "main", "prefix": "COPY"})
    assert shell.review["project_clone"].outcome == outcome
    assert shell.review["project_remote_url"] == source
    assert shell.review["project_clone"].publish is None
    assert shell.result.project_checkout_github_repo == "source/widgets"
    assert git(root, "remote", "get-url", "origin") == source
