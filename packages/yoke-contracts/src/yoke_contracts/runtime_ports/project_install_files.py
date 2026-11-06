"""Runtime interface for files."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectInstallFiles(Protocol):
    """Operations and values supplied by the executing adapter."""

    HOOK_MERGE_TARGETS: Any
    MANIFEST_REL: Any
    MANIFEST_SCHEMA: Any
    MODE_COPY: Any
    MODE_KEY: Any
    MODE_SOURCE_LINK: Any
    ProjectInstallError: type[Any]
    apply_contract_files: Callable[..., Any]
    apply_files: Callable[..., Any]
    assert_file_targets_plannable: Callable[..., Any]
    assert_resolved_targets_within: Callable[..., Any]
    assert_safe_bundle_paths: Callable[..., Any]
    assert_safe_contract_paths: Callable[..., Any]
    load_manifest: Callable[..., Any]
    load_manifest_path: Callable[..., Any]
    manifest_path: Callable[..., Any]
    prune_files: Callable[..., Any]
    remove_empty_parents: Callable[..., Any]
    resolve_repo_root: Callable[..., Any]
    sha256_text: Callable[..., Any]
    validate_manifest: Callable[..., Any]
    write_manifest: Callable[..., Any]


def get_project_install_files() -> ProjectInstallFiles:
    return cast(ProjectInstallFiles, load_port("project_install_files", ProjectInstallFiles))
