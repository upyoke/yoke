"""Uninstall removes the board art setup wrote, and keeps an operator's edit."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import onboard_wizard_board_art_apply as art_apply
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import uninstall_commit
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_cli.project_install.uninstall import uninstall
from yoke_contracts.project_contract.board_art import generate_default_variants
from yoke_core.domain.project_install_test_helpers import make_bundle

ART_REL = ".yoke/board-art"
LOCAL_EDIT_WARNING = f"{ART_REL} has local modifications"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "--no-verify", "-q", "-m", message)


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a, **_k: {"value": "main"})
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    (root / ".gitignore").write_text(".yoke/install-manifest.json\n")
    apply_bundle(root, make_bundle(), source="test")
    _commit(root, "Install operating layer")
    return root


def _wizard_writes_art(root: Path) -> str:
    variants = generate_default_variants("EXT", seed_text="seed")
    art_apply.write_board_art(root, "EXT", variants)
    _commit(root, art_apply.BOARD_ART_COMMIT_MESSAGE)
    return (root / ART_REL).read_text(encoding="utf-8")


def test_uninstall_removes_the_art_the_wizard_wrote(installed: Path) -> None:
    art = _wizard_writes_art(installed)
    record = files_layer.load_manifest(installed)["contract_files"][ART_REL]
    assert record == files_layer.sha256_text(art)

    report = uninstall(installed)

    assert ART_REL in report["contract_files_removed"]
    assert ART_REL not in report["contract_files_preserved_modified"]
    assert not any(LOCAL_EDIT_WARNING in warning for warning in report["warnings"])
    assert not (installed / ART_REL).exists()


def test_uninstall_preserves_an_edit_made_after_the_wizard(installed: Path) -> None:
    art = _wizard_writes_art(installed)
    (installed / ART_REL).write_text(art + "\n## Mine\n", encoding="utf-8")
    _commit(installed, "Operator edits board art")

    report = uninstall(installed)

    assert ART_REL in report["contract_files_preserved_modified"]
    assert any(LOCAL_EDIT_WARNING in warning for warning in report["warnings"])
    assert (installed / ART_REL).read_text(encoding="utf-8").endswith("## Mine\n")


def test_wizard_refuses_art_the_manifest_does_not_record(installed: Path) -> None:
    manifest = files_layer.load_manifest(installed)
    manifest["contract_files"].pop(ART_REL)
    files_layer.write_manifest(installed, manifest)
    before = (installed / ART_REL).read_text(encoding="utf-8")

    with pytest.raises(ProjectInstallError, match="contract_file_unrecorded") as exc:
        art_apply.write_board_art(installed, "EXT", [])

    assert "yoke project refresh" in str(exc.value)
    assert (installed / ART_REL).read_text(encoding="utf-8") == before


def test_wizard_refuses_a_checkout_with_no_install_manifest(tmp_path: Path) -> None:
    with pytest.raises(ProjectInstallError, match="contract_file_unrecorded"):
        art_apply.write_board_art(tmp_path, "EXT", [])

    assert not (tmp_path / ART_REL).exists()
