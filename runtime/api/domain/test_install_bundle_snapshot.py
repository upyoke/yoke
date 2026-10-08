"""Byte identity and wheel coverage of the packaged install source tree."""

from pathlib import Path
import hashlib
import pytest
from yoke_core.domain import install_bundle, install_bundle_tree_sync

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_ROOT = REPO_ROOT / install_bundle_tree_sync.PACKAGED_TREE_REL
INSTALL_BUNDLE_SOURCE_DIRS = install_bundle.INSTALL_BUNDLE_SOURCE_DIRS
PYPROJECT = REPO_ROOT / "packages/yoke-core/pyproject.toml"


def _assert_same_file(source: Path, packaged: Path) -> None:
    source_bytes = source.read_bytes()
    packaged_bytes = packaged.read_bytes()
    if source_bytes == packaged_bytes:
        return
    shared_length = min(len(source_bytes), len(packaged_bytes))
    first_difference = next(
        (
            offset
            for offset in range(shared_length)
            if source_bytes[offset] != packaged_bytes[offset]
        ),
        shared_length,
    )
    pytest.fail(
        "install bundle content drift: "
        f"{source.relative_to(REPO_ROOT).as_posix()} != "
        f"{packaged.relative_to(REPO_ROOT).as_posix()}; "
        f"first_difference={first_difference}, "
        f"source_bytes={len(source_bytes)}, packaged_bytes={len(packaged_bytes)}, "
        f"source_sha256={hashlib.sha256(source_bytes).hexdigest()}, "
        f"packaged_sha256={hashlib.sha256(packaged_bytes).hexdigest()}",
        pytrace=False,
    )


def test_packaged_install_bundle_tree_matches_source_inputs() -> None:
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        source = REPO_ROOT / rel
        packaged = PACKAGED_ROOT / rel
        source_files = sorted(
            path.relative_to(source).as_posix()
            for path in source.rglob("*")
            if path.is_file() and not install_bundle.is_bundle_junk_path(path)
        )
        packaged_files = sorted(
            path.relative_to(packaged).as_posix()
            for path in packaged.rglob("*")
            if path.is_file() and not install_bundle.is_bundle_junk_path(path)
        )
        assert packaged_files == source_files
        for file_rel in source_files:
            _assert_same_file(source / file_rel, packaged / file_rel)


def test_bundle_file_drift_reports_metadata_without_dumping_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "runtime.api.domain.test_install_bundle_snapshot.REPO_ROOT",
        tmp_path,
    )
    source = tmp_path / "source" / "agent.md"
    packaged = tmp_path / "packaged" / "agent.md"
    source.parent.mkdir()
    packaged.parent.mkdir()
    source.write_text("source-private-content", encoding="utf-8")
    packaged.write_text("packaged-private-content", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as raised:
        _assert_same_file(source, packaged)

    message = str(raised.value)
    assert "first_difference=" in message
    assert "source_sha256=" in message
    assert "packaged_sha256=" in message
    assert "private-content" not in message


def test_detect_drift_agrees_the_snapshot_is_in_sync() -> None:
    # The materializer's drift detector (which HC-install-bundle-drift consumes)
    # must agree with the byte-level invariant above — one code path guards the
    # shipped wheel, so a divergence between the two is itself the bug.
    assert install_bundle_tree_sync.detect_drift(target_root=REPO_ROOT) == []


def test_pyproject_package_data_covers_every_source_dir() -> None:
    # setuptools can only ship files it globs. If a source dir is added to
    # INSTALL_BUNDLE_SOURCE_DIRS (and materialized) but not globbed here, the
    # wheel silently omits it — drift the byte test can't see (the packaged
    # tree matches, but the wheel wouldn't carry it). Keep the two in lockstep.
    text = PYPROJECT.read_text("utf-8")
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        assert f'"{rel}/**/*"' in text, (
            f"pyproject package-data is missing a glob for {rel!r}; the wheel "
            f"would not ship it"
        )
