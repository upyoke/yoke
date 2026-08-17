"""Artifact-bound validation for a freshly built Yoke wheelhouse."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Callable

from yoke_core.tools import package_index, wheel_module_completeness


INSTALLED_BOOT_MODULES = (
    "yoke_core.api.server_entrypoint",
    "yoke_core.domain.schema_init",
)


def assert_core_wheel_completeness(repo_root: Path, wheelhouse: Path) -> None:
    """Compare the built core wheel with its production source modules."""
    wheel = _core_wheel(wheelhouse)
    package_root = repo_root / "packages" / "yoke-core" / "src" / "yoke_core"
    wheel_module_completeness.assert_wheel_module_completeness(package_root, wheel)


def verify_product_wheel_boot(
    wheelhouse: Path,
    *,
    create_venv: Callable[[Path], None],
    run: Callable[..., None],
) -> None:
    """Install from the wheel closure and import the real server boot path."""
    with tempfile.TemporaryDirectory(prefix="yoke-wheel-boot-") as work:
        root = Path(work)
        create_venv(root)
        python = root / "bin" / "python"
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "yoke-core",
            ],
            cwd=root,
        )
        run(
            [str(python), "-m", "yoke_core.tools.product_wheel_validation"],
            cwd=root,
        )


def verify_installed_boot() -> None:
    """Import every module required before an installed server can serve."""
    for module in INSTALLED_BOOT_MODULES:
        importlib.import_module(module)


def _core_wheel(wheelhouse: Path) -> Path:
    matches = [
        wheelhouse / record.filename
        for record in package_index.read_wheel_records(wheelhouse)
        if record.canonical_name == "yoke-core"
    ]
    if len(matches) != 1:
        raise wheel_module_completeness.WheelModuleCompletenessError(
            f"wheelhouse must contain exactly one yoke-core wheel, found {len(matches)}"
        )
    return matches[0]


def main() -> int:
    verify_installed_boot()
    print("installed yoke-core boot imports passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
