"""Registered checkouts exempt live reads without weakening test isolation."""

from pathlib import Path
import shlex
import subprocess

import pytest

from yoke_contracts.hook_runner import local_privacy_guard as guard
from yoke_contracts.hook_runner.local_privacy_messages import HOME_DISCOVERY
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema_connections import MachineConfigContractError
from yoke_core.domain import lint_local_privacy
from yoke_harness.hooks import local_policies
from yoke_harness.hooks.local_policy_common import ADVISORY, NOOP


@pytest.fixture
def checkout(tmp_path):
    home = tmp_path / "home"
    repo = home / "Documents" / "checkout"
    repo.mkdir(parents=True)
    (repo / "docs").mkdir()
    (home / "Documents" / "outside").mkdir()
    (repo / "escape").symlink_to(
        home / "Documents" / "outside", target_is_directory=True
    )
    return home, repo


@pytest.mark.parametrize(
    "command",
    [
        "rg token ~/Documents/checkout/docs",
        "rg --files ~/Documents/checkout",
        "rg token docs",
        "rg token",
        "find",
        "fd token",
        "grep -R token",
        "zsh -lc 'rg token docs'",
        "cat ~/Documents/checkout/docs/spec.md",
        "cd docs && rg token .",
    ],
)
def test_reads_inside_registered_checkout_are_exempt(checkout, command):
    home, repo = checkout
    assert (
        guard.classify_shell_command(
            command, home=home, cwd=repo, checkout_roots=(str(repo),)
        )
        is None
    )


@pytest.mark.parametrize(
    "target",
    [
        "~/Documents",
        "~/Documents/checkout-sibling",
        "~/Documents/checkout/..",
        "~/Documents/checkout/docs/../../outside",
        "~/Documents/checkout/escape",
    ],
)
def test_outside_and_escaping_paths_still_warn(checkout, target):
    home, repo = checkout
    finding = guard.classify_shell_command(
        f"rg token {target}", home=home, cwd=repo, checkout_roots=(str(repo),)
    )
    assert finding is not None
    assert (finding.category, finding.service) == (HOME_DISCOVERY, "Documents")


def test_other_protected_paths_never_resolve_on_disk(checkout, monkeypatch):
    home, repo = checkout

    def unexpected_resolution(*args, **kwargs):
        pytest.fail("unrelated protected paths must not touch the filesystem")

    monkeypatch.setattr(guard.os.path, "realpath", unexpected_resolution)
    finding = guard.classify_shell_command(
        "rg token ~/Documents/outside", home=home, checkout_roots=(str(repo),)
    )
    assert (finding.category, finding.service) == (HOME_DISCOVERY, "Documents")


@pytest.mark.parametrize(
    "config_failure",
    [None, OSError, machine_config.MachineConfigError, MachineConfigContractError],
)
def test_both_live_callers_load_mapping_and_fail_closed(
    checkout, monkeypatch, config_failure
):
    home, repo = checkout
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    config = {
        "active_env": "test",
        "connection_projects": {"test": [{"checkout": str(repo), "project_id": 1}]},
    }

    def load_config():
        if config_failure:
            raise config_failure("unreadable")
        return config

    monkeypatch.setattr(machine_config, "load_config", load_config)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "rg token docs"},
        "cwd": str(repo),
    }
    engine = lint_local_privacy.evaluate_payload(lint_local_privacy._context(payload))
    product = local_policies.lint_local_privacy(payload, parse_shell("rg token docs"))
    if config_failure:
        assert engine[1] == "advisory"
        assert product.outcome == ADVISORY
    else:
        assert engine is None
        assert product.outcome == NOOP


def test_missing_config_does_not_exempt_checkout(checkout, monkeypatch):
    home, repo = checkout
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(machine_config, "load_config", lambda: {})
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "rg token docs"},
        "cwd": str(repo),
    }
    assert (
        lint_local_privacy.evaluate_payload(lint_local_privacy._context(payload))[1]
        == "advisory"
    )
    assert (
        local_policies.lint_local_privacy(payload, parse_shell("rg token docs")).outcome
        == ADVISORY
    )


def test_test_tripwire_blocks_even_a_registered_checkout(checkout, monkeypatch):
    home, repo = checkout
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda: {
            "active_env": "test",
            "connection_projects": {"test": [{"checkout": str(repo), "project_id": 1}]},
        },
    )
    with pytest.raises(pytest.fail.Exception):
        subprocess.run(["rg", "token", str(repo)], check=False)
    finding = guard.classify_subprocess_args(
        shlex.join(["rg", "token", str(repo)]), home=home, cwd=repo
    )
    assert (finding.category, finding.service) == (HOME_DISCOVERY, "Documents")
