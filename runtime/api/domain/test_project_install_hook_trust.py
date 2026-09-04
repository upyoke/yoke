"""Project install mints trust for the exact Codex hooks it authors."""

from __future__ import annotations

import pytest

from yoke_cli.project_install.hook_trust_report import REPORT_KEY
from yoke_cli.project_install import runner
from yoke_contracts.codex_hook_trust_store import inspect_hook_file_trust
from yoke_contracts.harness_hook_approval import HARNESS_HOOK_APPROVAL
from yoke_core.domain.project_install import apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    codex_hooks,
    entry,
    make_bundle,
)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _codex_lines(report) -> list[str]:
    surface = HARNESS_HOOK_APPROVAL["codex"]["trust_surface"]
    return [line for line in report[REPORT_KEY] if surface in line]


def _codex_home(monkeypatch, tmp_path):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def test_fresh_write_mints_trust_without_manual_approval_teaching(
    repo,
    monkeypatch,
    tmp_path,
):
    _codex_home(monkeypatch, tmp_path)
    report = apply_bundle(repo, make_bundle(), source="test")
    trust = runner._mint_codex_hook_trust(repo)

    assert _codex_lines(report) == []
    assert trust["hook_entries_written"] > 0
    assert inspect_hook_file_trust(repo / ".codex/hooks.json").approved is True


def test_updating_the_glue_replaces_the_previous_hashes(
    repo,
    monkeypatch,
    tmp_path,
):
    _codex_home(monkeypatch, tmp_path)
    apply_bundle(repo, make_bundle(), source="test")
    runner._mint_codex_hook_trust(repo)

    updated = codex_hooks()
    updated["PreToolUse"].append(entry("yoke hook evaluate PreToolUse", "Edit"))
    report = apply_bundle(repo, make_bundle(codex=updated), source="test")
    trust = runner._mint_codex_hook_trust(repo)

    assert _codex_lines(report) == []
    assert trust["hook_entries_removed"] > 0
    assert inspect_hook_file_trust(repo / ".codex/hooks.json").approved is True


def test_a_reconcile_that_changed_nothing_rewrites_nothing(
    repo,
    monkeypatch,
    tmp_path,
):
    _codex_home(monkeypatch, tmp_path)
    apply_bundle(repo, make_bundle(), source="test")
    runner._mint_codex_hook_trust(repo)

    report = apply_bundle(repo, make_bundle(), source="test")
    trust = runner._mint_codex_hook_trust(repo)

    assert report[REPORT_KEY] == []
    assert trust["changed"] is False


def test_install_without_codex_hooks_records_an_inert_skip(repo, monkeypatch, tmp_path):
    home = _codex_home(monkeypatch, tmp_path)

    trust = runner._mint_codex_hook_trust(repo)

    assert trust["changed"] is False
    assert trust["skipped_reason"] == (
        f"Codex hooks file is absent: {repo / '.codex/hooks.json'}"
    )
    assert not (home / "config.toml").exists()


def test_config_write_refusal_names_path_and_recovery(repo, monkeypatch, tmp_path):
    home = _codex_home(monkeypatch, tmp_path)
    config = home / "config.toml"
    config.write_text("[broken", encoding="utf-8")
    apply_bundle(repo, make_bundle(), source="test")

    with pytest.raises(runner.ProjectInstallError) as caught:
        runner._mint_codex_hook_trust(repo)

    message = str(caught.value)
    assert str(repo / ".codex/hooks.json") in message
    assert f"re-trust in Codex: open Codex in {repo}, Hooks, Trust" in message
