"""Tests for the seed-if-missing project-contract pass of project install.

Drives :func:`project_install.apply_bundle` with fake bundles against a
tmp repo, covering seeding, refresh preservation/recreation, adoption
self-heal, manifest tracking, and contract path/policy refusal. Managed
``files``/manifest mechanics live in ``test_project_install.py``;
hook-merge and uninstall specifics in ``test_project_install_hooks.py``.
"""

from __future__ import annotations

import json
import hashlib

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_CONTRACT_FILES,
    OMIT_CONTRACT,
    contract_entry,
    make_bundle,
)

MANIFEST_REL = ".yoke/install-manifest.json"


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def test_fresh_install_seeds_contract_files(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    for entry in DEFAULT_CONTRACT_FILES:
        assert (repo / entry["path"]).read_text("utf-8") == entry["content"]
    assert sorted(report["contract_files_written"]) == sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES
    )
    assert report["contract_files_existing"] == []
    manifest = _manifest(repo)
    assert set(manifest["contract_files"]) == {
        e["path"] for e in DEFAULT_CONTRACT_FILES
    }
    assert set(manifest["contract_files"]).isdisjoint(manifest["files"])


def test_refresh_never_overwrites_edited_contract_files(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    edited = {
        ".yoke/lint-config": "lint_main_commit=warn  # allow-warn\n",
        ".yoke/board.json": '{"art_override": "frontier"}\n',
        ".yoke/board-art": "## Master Map\n⬜⬛\n",
    }
    for rel, content in edited.items():
        (repo / rel).write_text(content, encoding="utf-8")

    report = apply_bundle(
        repo, make_bundle(), operation="refresh", source="test"
    )

    assert report["contract_files_written"] == []
    assert sorted(report["contract_files_existing"]) == sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES
    )
    for rel, content in edited.items():
        assert (repo / rel).read_text("utf-8") == content
    assert report["warnings"] == []


def test_refresh_recreates_missing_contract_file(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    missing = DEFAULT_CONTRACT_FILES[1]
    (repo / missing["path"]).unlink()

    report = apply_bundle(
        repo, make_bundle(), operation="refresh", source="test"
    )

    assert report["contract_files_written"] == [missing["path"]]
    assert (repo / missing["path"]).read_text("utf-8") == missing["content"]


def test_preexisting_contract_file_is_never_recorded_as_installer_created(
    repo,
) -> None:
    rel = DEFAULT_CONTRACT_FILES[0]["path"]
    (repo / ".yoke").mkdir()
    (repo / rel).write_text("project-authored\n", encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), source="test")

    assert rel not in report["contract_files_written"]
    assert rel in report["contract_files_existing"]
    assert (repo / rel).read_text("utf-8") == "project-authored\n"
    assert rel not in _manifest(repo)["contract_files"]


def test_contract_entry_leaving_bundle_stays_tracked_for_uninstall(
    repo,
) -> None:
    apply_bundle(repo, make_bundle(), source="test")

    apply_bundle(
        repo, make_bundle(contract=DEFAULT_CONTRACT_FILES[:1]),
        operation="refresh", source="test",
    )

    manifest = _manifest(repo)
    assert set(manifest["contract_files"]) == {
        e["path"] for e in DEFAULT_CONTRACT_FILES
    }, "seeded files that left the bundle remain tracked for uninstall"
    for entry in DEFAULT_CONTRACT_FILES:
        assert (repo / entry["path"]).is_file(), "never pruned on refresh"


def test_bundle_without_contract_key_is_tolerated(repo) -> None:
    report = apply_bundle(
        repo, make_bundle(contract=OMIT_CONTRACT), source="test"
    )

    assert report["contract_files_written"] == []
    assert report["contract_files_existing"] == []
    assert report["contract_files_adopted"] == []
    assert _manifest(repo)["contract_files"] == {}


def test_existing_file_byte_identical_to_seed_is_adopted(repo) -> None:
    seed = DEFAULT_CONTRACT_FILES[0]
    (repo / ".yoke").mkdir()
    (repo / seed["path"]).write_text(seed["content"], encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["contract_files_adopted"] == [seed["path"]]
    assert seed["path"] in report["contract_files_existing"]
    assert seed["path"] not in report["contract_files_written"]
    assert seed["path"] in _manifest(repo)["contract_files"]

    uninstall_report = project_install.uninstall(repo)
    assert seed["path"] in uninstall_report["contract_files_removed"], (
        "adopted byte-identical content is removable — nothing is lost"
    )


def test_refresh_readopts_after_manifest_lost_contract_key(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    # Simulate an older CLI's whole-object manifest rewrite dropping the key.
    manifest = _manifest(repo)
    del manifest["contract_files"]
    (repo / MANIFEST_REL).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    edited = DEFAULT_CONTRACT_FILES[1]["path"]
    (repo / edited).write_text("project tuning\n", encoding="utf-8")

    report = apply_bundle(
        repo, make_bundle(), operation="refresh", source="test"
    )

    pristine = sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES if e["path"] != edited
    )
    assert sorted(report["contract_files_adopted"]) == pristine, (
        "pristine seeds are re-adopted; the edited file stays unrecorded"
    )
    assert sorted(_manifest(repo)["contract_files"]) == pristine
    assert (repo / edited).read_text("utf-8") == "project tuning\n"


def test_unknown_manifest_keys_survive_refresh(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    manifest = _manifest(repo)
    manifest["future_field"] = {"from": "a newer CLI"}
    (repo / MANIFEST_REL).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    assert _manifest(repo)["future_field"] == {"from": "a newer CLI"}, (
        "unknown top-level manifest keys are carried forward on rewrite"
    )


def test_unknown_contract_install_policy_is_refused(repo) -> None:
    entry = dict(
        contract_entry(".yoke/lint-config", "x\n"),
        install_policy="update_if_unmodified",
    )

    with pytest.raises(ProjectInstallError) as exc_info:
        apply_bundle(repo, make_bundle(contract=[entry]), source="test")
    assert "update_if_unmodified" in str(exc_info.value)
    assert "seed_if_missing" in str(exc_info.value)
    assert not (repo / MANIFEST_REL).exists()


def test_uninstall_accepts_safe_legacy_contract_and_strategy_paths(repo) -> None:
    contract_rel = ".sunday/lint-config"
    strategy_rel = ".sunday/strategy/MISSION.md"
    contract_content = "legacy policy\n"
    strategy_content = "legacy strategy\n"
    for rel, content in (
        (contract_rel, contract_content),
        (strategy_rel, strategy_content),
    ):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (repo / ".yoke").mkdir()
    (repo / MANIFEST_REL).write_text(
        json.dumps({
            "manifest_schema": 1,
            "contract_files": {
                contract_rel: hashlib.sha256(
                    contract_content.encode("utf-8")
                ).hexdigest(),
            },
            "strategy_files": {
                strategy_rel: hashlib.sha256(
                    strategy_content.encode("utf-8")
                ).hexdigest(),
            },
        }),
        encoding="utf-8",
    )

    report = project_install.uninstall(repo)

    assert report["contract_files_removed"] == [contract_rel]
    assert report["strategy_files_preserved"] == [strategy_rel]
    assert not (repo / contract_rel).exists()
    assert (repo / strategy_rel).read_text(encoding="utf-8") == strategy_content


@pytest.mark.parametrize("bad_path", [
    "../escape",
    "/etc/absolute",
    ".claude/skills/yoke/x.md",
    ".yoke/install-manifest.json",
    ".yoke/BOARD.md",
    ".yoke/BOARD.md.ts",
    ".yoke/board-art.example",
    ".yoke/backups/dump.sql",
])
def test_unsafe_contract_paths_are_refused(repo, bad_path) -> None:
    bundle = make_bundle(contract=[contract_entry(bad_path, "x\n")])

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, bundle, source="test")
    assert not (repo / MANIFEST_REL).exists()
