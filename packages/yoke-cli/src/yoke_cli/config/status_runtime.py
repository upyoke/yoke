"""Installed runtime diagnostics used by yoke status."""

from __future__ import annotations

import shutil
import sys
from typing import Any, Callable, Mapping

from yoke_cli.config import install_binding
from yoke_contracts.machine_config import schema as contract


def build_runtime_status(
    connection: Mapping[str, Any],
    *,
    required_imports: tuple[str, ...],
    runtime_packages: tuple[str, ...],
    import_status: Callable[[str], dict[str, Any]],
    package_version: Callable[..., str],
    issue: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    """Report product imports and distribution versions for one connection."""
    imports = {name: import_status(name) for name in required_imports}
    if connection.get("transport") in contract.POSTGRES_TRANSPORTS:
        imports["yoke_core"] = import_status("yoke_core")
        imports["psycopg"] = import_status("psycopg")
    source_bound = (
        install_binding.detect().get("kind") == install_binding.KIND_SOURCE_CHECKOUT
    )
    package_versions = {
        name: package_version(name, source_bound=source_bound)
        for name in runtime_packages
    }
    issues = []
    for name, item in imports.items():
        if item["available"]:
            continue
        hint = (
            "Repair the install so the yoke-core engine and psycopg "
            "import (local-postgres connections dispatch in-process), "
            "or switch to an HTTPS env."
            if name in {"yoke_core", "psycopg"}
            else "Install the Yoke product packages."
        )
        issues.append(
            issue(
                "error",
                "import_missing",
                f"required package import failed: {name}",
                hint,
            )
        )
    return {
        "python_executable": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "yoke_executable": shutil.which("yoke") or "",
        "imports": imports,
        "package_versions": package_versions,
        "issues": issues,
    }


__all__ = ["build_runtime_status"]
