"""The built yoke-core wheel carries the install-bundle tree of its sources.

The repository commits only the sources; ``packages/yoke-core/setup.py``
builds ``yoke_core/install_bundle_tree`` into the wheel. This proof compares
the wheel with an independent oracle: the tracked source files, symlinks
followed, plus the managed region of each root doctrine file.
"""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from yoke_contracts.project_contract.managed_block import MANAGED_BLOCK_END
from yoke_core.domain.install_bundle import INSTALL_BUNDLE_SOURCE_DIRS
from yoke_core.domain.install_bundle_sources import INSTALL_BUNDLE_SOURCE_FILES

REPO_ROOT = Path(__file__).resolve().parents[3]
TREE_PREFIX = "yoke_core/install_bundle_tree/"


def _tracked(rel: str) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", rel],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.decode("utf-8")
    return [path for path in listed.split("\0") if path]


def _expected_tree() -> dict[str, bytes]:
    expected = {}
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        for path in _tracked(rel):
            if (REPO_ROOT / path).is_file():
                expected[path] = (REPO_ROOT / path).read_bytes()
    marker = MANAGED_BLOCK_END.encode("utf-8")
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        data = (REPO_ROOT / rel).read_bytes()
        expected[rel] = data[: data.index(marker) + len(marker)] + b"\n"
    return expected


def _wheel_tree(wheelhouse: Path) -> dict[str, bytes]:
    wheel = next(wheelhouse.glob("yoke_core-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        return {
            name.removeprefix(TREE_PREFIX): archive.read(name)
            for name in archive.namelist()
            if name.startswith(TREE_PREFIX) and not name.endswith("/")
        }


def _digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def test_wheel_install_bundle_tree_is_byte_identical_to_sources(
    product_wheelhouse: Path,
) -> None:
    shipped = _wheel_tree(product_wheelhouse)
    assert shipped.pop("__init__.py").startswith(b'"""Packaged install-bundle')
    expected = _expected_tree()

    differing = sorted(
        rel
        for rel in set(shipped) | set(expected)
        if shipped.get(rel) != expected.get(rel)
    )

    if differing:
        detail = "; ".join(
            f"{rel}: wheel={_digest(shipped.get(rel))} "
            f"source={_digest(expected.get(rel))}"
            for rel in differing[:20]
        )
        pytest.fail(
            f"{len(differing)} install-bundle tree file(s) differ between the "
            f"built wheel and the tracked sources: {detail}",
            pytrace=False,
        )
    assert expected


def test_wheel_tree_omits_repo_internals_of_root_doctrine(
    product_wheelhouse: Path,
) -> None:
    shipped = _wheel_tree(product_wheelhouse)

    agents = shipped["AGENTS.md"].decode("utf-8")
    assert agents.endswith(f"{MANAGED_BLOCK_END}\n")
    assert "## Yoke repository" not in agents
