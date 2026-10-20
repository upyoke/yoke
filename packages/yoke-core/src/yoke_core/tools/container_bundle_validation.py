"""Exercise project-bundle rendering from the image's installed packaged tree."""

from __future__ import annotations

import argparse
import json
import os

from yoke_contracts.project_contract.installed_layer import (
    FULL_COMMIT_PATTERN,
    INSTALLED_LAYER_RECEIPT_REL,
)
from yoke_core.domain.install_bundle_sources import HARNESS_MANIFEST_SOURCES


class ContainerBundleError(AssertionError):
    """The image's rendered bundle is incomplete or misattributed."""


def verify_project_bundle(build_sha: str | None = None) -> dict:
    """Render from the real server tree, replacing only project database state.

    The server tree must be the installed wheel's packaged tree. A full
    ``YOKE_BUILD_SHA`` must reach the receipt as ``source_build``; any other
    build value must leave the receipt unattributed.
    """
    from unittest.mock import Mock, patch

    from yoke_core.domain import install_bundle, install_bundle_project
    from yoke_core.domain import project_policy_capabilities

    root = install_bundle.server_tree_root()
    if root.resolve() != install_bundle.packaged_tree_root().resolve():
        raise ContainerBundleError(
            f"IMAGE_SERVER_TREE_NOT_PACKAGED: the image serves {root}, not the "
            "installed wheel's packaged tree. Remove YOKE_SERVER_TREE_ROOT from "
            "the image environment and rebuild."
        )
    # Image construction has no tenant database. Keep every filesystem reader
    # and renderer real while supplying the project-owned database boundaries.
    with (
        patch.object(
            install_bundle_project,
            "_project_row",
            return_value=("image-check", "Image check", "main"),
        ),
        patch.object(install_bundle_project, "_strategy_files", return_value=[]),
        patch.object(
            project_policy_capabilities,
            "ensure_default_policy_capabilities",
            return_value={},
        ),
    ):
        bundle = install_bundle_project.build_project_bundle(1, Mock())
    files = {entry["path"]: entry["content"] for entry in bundle["files"]}
    for relative in HARNESS_MANIFEST_SOURCES:
        installed = relative.replace("runtime/harness/", ".yoke/harness/", 1)
        assert files[installed].encode() == (root / relative).read_bytes()
    assert files[".yoke/docs/index.md"]
    assert files[".agents/skills/yoke/help/SKILL.md"]
    assert bundle["managed_markdown"]["blocks"]["doctrine"]
    build = (
        os.environ.get("YOKE_BUILD_SHA", "") if build_sha is None else build_sha
    ).strip()
    expected = build if FULL_COMMIT_PATTERN.fullmatch(build) else ""
    recorded = json.loads(files[INSTALLED_LAYER_RECEIPT_REL]).get("source_build", "")
    if recorded != expected:
        raise ContainerBundleError(
            f"IMAGE_BUNDLE_BUILD_MISMATCH: the rendered receipt records "
            f"source_build={recorded or '<none>'} but YOKE_BUILD_SHA="
            f"{build or '<unset>'} expects {expected or '<none>'}. Build the "
            "image with YOKE_BUILD_SHA set to the full 40-character source commit."
        )
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify")
    parser.parse_args(argv)
    bundle = verify_project_bundle()
    print(f"container project bundle passed: {len(bundle['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
