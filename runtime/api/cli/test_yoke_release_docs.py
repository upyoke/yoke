"""Release artifact documentation guards."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_BUILD_COMMAND = "uv run python -m yoke_core.tools.build_release"

# The public installer is the only canonical user-facing install surface. It
# owns channel resolution, product-package lockstep, and safe index precedence.
CANONICAL_INSTALL_CURL = "curl -fsSL https://upyoke.com/install | sh"
UNSAFE_UV_UPGRADE = "uv tool upgrade yoke-cli"
UNSAFE_MULTI_INDEX_INSTALL = "uv tool install yoke-cli"
INSTALL_CONTRACT_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "local-setup.md",
    ROOT / "docs" / "onboard-external-project.md",
)
# Retired install-model vocabulary that must not return to the live docs.
RETIRED_INSTALL_PROSE = (
    "wheelhouse",
    "Yoke-owned venv",
    "~/.local/bin",
    "Python 3.10+",
)


def test_package_index_docs_teach_release_builder_not_manual_index() -> None:
    text = (ROOT / "packaging" / "package-index" / "README.md").read_text(
        encoding="utf-8",
    )

    assert CANONICAL_BUILD_COMMAND in text
    assert CANONICAL_INSTALL_CURL in text
    assert UNSAFE_MULTI_INDEX_INSTALL not in text
    assert "--extra-index-url" not in text
    assert "python3 -m pip wheel --wheel-dir" not in text
    assert "PYTHONPATH=packages/yoke-core/src" not in text
    assert "python3 -m yoke_core.tools.package_index" not in text


def test_source_dev_docs_name_release_builder_boundary() -> None:
    for path in (
        ROOT / "docs" / "local-setup.md",
        ROOT / "docs" / "onboard-external-project.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert CANONICAL_BUILD_COMMAND in text


def test_install_docs_teach_public_installer_contract() -> None:
    for path in INSTALL_CONTRACT_DOCS:
        text = path.read_text(encoding="utf-8")
        assert CANONICAL_INSTALL_CURL in text, path
        assert UNSAFE_MULTI_INDEX_INSTALL not in text, path
        assert "public PyPI" in text, path
        assert "ambient uv index settings" in text, path


def test_install_docs_teach_lockstep_upgrade_not_single_package_upgrade() -> None:
    for path in INSTALL_CONTRACT_DOCS:
        text = path.read_text(encoding="utf-8")
        assert UNSAFE_UV_UPGRADE not in text, path
        assert "rerun the same curl installer" in text, path


def test_install_docs_purge_retired_wheelhouse_venv_model() -> None:
    for path in INSTALL_CONTRACT_DOCS:
        text = path.read_text(encoding="utf-8")
        for retired in RETIRED_INSTALL_PROSE:
            assert retired not in text, f"{path}: retired install prose {retired!r}"
