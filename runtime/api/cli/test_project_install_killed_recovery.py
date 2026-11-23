"""A killed install resumes to a clean checkout, or refuses to report success."""

from __future__ import annotations

import shutil

import pytest

from runtime.api.cli.project_install_recovery_test_support import _commit, _file, _git
from yoke_cli.project_install import checkout_gate, instruction_discovery
from yoke_cli.project_install import owned_cleanup, skill_discovery
from yoke_cli.project_install import install_recovery as recovery
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.file_line_managed_exceptions import (
    ensure_managed_file_line_exceptions,
    planned_config_text,
)
from yoke_contracts.project_contract.file_line_policy import PROJECT_CONFIG_REL
from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_core.domain.project_contract import bundle_contract_files
from yoke_core.domain.project_install_test_helpers import make_bundle


def _bundle() -> dict:
    bundle = make_bundle(contract=bundle_contract_files("Demo"))
    bundle["managed_markdown"] = {
        "blocks": {"main": "# Yoke rules\n"},
        "targets": [{"path": "AGENTS.md", "block": "main"}],
    }
    return bundle


@pytest.fixture
def killed(tmp_path, monkeypatch):
    """A checkout whose install wrote everything and died before its commit."""
    monkeypatch.setattr(instruction_discovery.shutil, "which", lambda _: None)
    _git(tmp_path, "init")
    _file(tmp_path, "README.md", "project\n")
    _commit(tmp_path, "Create project")
    apply_bundle(tmp_path, _bundle(), retain_pending=True)
    assert recovery.pending(tmp_path)
    return tmp_path


def test_recovery_accepts_the_installers_own_config_edit(killed):
    assert "AGENTS.md" in (killed / PROJECT_CONFIG_REL).read_text("utf-8")
    assert recovery.recoverable_checkout(killed)
    assert recovery.unclaimed_dirt(killed, True) == []


def test_recovery_removes_a_killed_writes_staging_file(killed):
    planned = killed / PROJECT_CONFIG_REL
    leftover = planned.with_name(f".{planned.name}i2iaao56")
    leftover.write_text("partial", encoding="utf-8")
    lookalike = planned.with_name(f".{planned.name}.mine")
    lookalike.write_text("mine", encoding="utf-8")

    assert not recovery.recoverable_checkout(killed)  # the lookalike stays dirty
    assert not leftover.exists() and lookalike.read_text("utf-8") == "mine"
    lookalike.unlink()
    assert recovery.recoverable_checkout(killed)


def test_a_tracked_file_named_like_a_staging_file_is_kept(killed):
    planned = killed / PROJECT_CONFIG_REL
    kept = planned.with_name(f".{planned.name}abcd1234")
    kept.write_text("tracked", encoding="utf-8")
    _git(killed, "add", "-f", str(kept.relative_to(killed)))

    recovery.recoverable_checkout(killed)

    assert kept.read_text("utf-8") == "tracked"


def test_retry_after_the_kill_commits_every_installer_path(killed):
    assert recovery.recoverable_checkout(killed)
    recovered = [
        checkout_gate._porcelain_path(line) for line in checkout_gate.porcelain(killed)
    ]
    report = apply_bundle(killed, _bundle(), retain_pending=True)
    report["files_recovered"] = recovered  # the runner claims them the same way
    checkout_gate.commit_touched_paths(killed, report)
    recovery.finish(killed, recovery.pending(killed))

    assert not recovery.pending(killed)
    assert not checkout_gate.porcelain(killed)


def test_a_local_edit_rejects_recovery_and_blocks_success(killed):
    config = killed / PROJECT_CONFIG_REL
    config.write_text(config.read_text("utf-8") + "# my edit\n", encoding="utf-8")
    assert not recovery.recoverable_checkout(killed)
    unclaimed = recovery.unclaimed_dirt(killed, False)
    assert PROJECT_CONFIG_REL in unclaimed and recovery.PENDING_REL not in unclaimed

    with pytest.raises(ProjectInstallError) as exc:
        recovery.refuse_unclaimed_dirt(killed, unclaimed)

    assert "install_recovery_incomplete" in str(exc.value)
    assert PROJECT_CONFIG_REL in str(exc.value)
    assert recovery.pending(killed)


def test_paths_committed_after_a_rejected_recovery_do_not_block(killed):
    unclaimed = recovery.unclaimed_dirt(killed, False)
    _git(killed, "add", "-A")
    _git(
        killed, "-c", "user.name=Owner", "-c", "user.email=owner@example.test",
        "-c", "core.hooksPath=/dev/null", "commit", "-m", "Keep the interrupted install",
    )

    recovery.refuse_unclaimed_dirt(killed, unclaimed)


def _skill_copy(root):
    rel = next(iter(skill_discovery.SKILL_DISCOVERY_LINKS))
    entry = root / rel
    source = (entry.parent / skill_discovery.SKILL_DISCOVERY_LINKS[rel]).resolve()
    if entry.is_symlink():
        entry.unlink()
    else:
        shutil.rmtree(entry)
    shutil.copytree(source, entry)
    return rel, entry


def test_a_killed_installs_own_skill_copy_is_still_its_own(killed):
    rel, entry = _skill_copy(killed)

    assert skill_discovery.entry_state(killed, rel) == skill_discovery.COPIED
    next(path for path in entry.rglob("*") if path.is_file()).unlink()  # killed mid-copy
    assert skill_discovery.entry_state(killed, rel) == skill_discovery.COPIED


@pytest.mark.parametrize("change", ["edited", "added"])
def test_an_operators_change_to_the_copy_stays_foreign(killed, change):
    rel, entry = _skill_copy(killed)
    if change == "edited":
        next(p for p in entry.rglob("*") if p.is_file()).write_text("mine", "utf-8")
    else:
        (entry / "my-notes.md").write_text("mine", encoding="utf-8")

    assert skill_discovery.entry_state(killed, rel) == skill_discovery.FOREIGN


def test_a_copy_without_an_interrupted_install_stays_foreign(killed):
    rel, _entry = _skill_copy(killed)
    (killed / recovery.PENDING_REL).unlink()

    assert skill_discovery.entry_state(killed, rel) == skill_discovery.FOREIGN


def test_registration_intent_survives_a_kill_for_its_own_config_only(killed, tmp_path):
    config = killed / "machine.json"

    assert not owned_cleanup.registration_intended(killed, config)
    owned_cleanup.intend_registration(killed, config)
    assert owned_cleanup.registration_intended(killed, config)
    assert not owned_cleanup.registration_intended(killed, killed / "other.json")


@pytest.mark.parametrize(
    "original", ["", "a=1", "a=1\n", "file_line_exception=AGENTS.md # why\n", "a=1\r\n"]
)
def test_planned_config_is_what_the_install_writes(tmp_path, original):
    config = tmp_path / PROJECT_CONFIG_REL
    config.parent.mkdir(parents=True)
    config.write_bytes(original.encode("utf-8"))
    read = config.read_text(encoding="utf-8")

    ensure_managed_file_line_exceptions(tmp_path, ["AGENTS.md"])

    assert config.read_bytes().decode("utf-8") == planned_config_text(read, ["AGENTS.md"])
