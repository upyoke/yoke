"""Artifact-bound validation for a freshly built Yoke wheelhouse."""

from __future__ import annotations

import builtins
import importlib
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator

import yoke_core
from yoke_core.tools import package_index, wheel_module_completeness


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
    """Install from the wheel closure and validate every shipped core module."""
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


def installed_core_module_names() -> tuple[str, ...]:
    """Derive every importable module from the installed ``yoke_core`` tree."""
    package_root = Path(yoke_core.__file__).resolve().parent
    members = wheel_module_completeness.source_runtime_members(package_root)
    return tuple(sorted(_module_name(member) for member in members))


def _module_name(member: str) -> str:
    path = PurePosixPath(member)
    parts = path.parts[:-1]
    if path.name != "__init__.py":
        parts = (*parts, path.stem)
    return ".".join(parts)


@contextmanager
def _record_missing_core_imports() -> Iterator[set[tuple[str, str]]]:
    """Record missing imports attempted and swallowed by core modules."""
    original_import = builtins.__import__
    missing: set[tuple[str, str]] = set()

    def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
        try:
            return original_import(name, globals, locals, fromlist, level)
        except ModuleNotFoundError as exc:
            requester = str((globals or {}).get("__name__") or "")
            if requester == "yoke_core" or requester.startswith("yoke_core."):
                missing.add((requester, str(exc.name or name)))
            raise

    builtins.__import__ = tracked_import
    try:
        yield missing
    finally:
        builtins.__import__ = original_import


def verify_installed_boot() -> tuple[str, ...]:
    """Import every installed core module and reject swallowed missing imports."""
    with _record_missing_core_imports() as missing:
        modules = installed_core_module_names()
        for module in modules:
            importlib.import_module(module)
    if missing:
        detail = ", ".join(
            f"{requester} -> {dependency}"
            for requester, dependency in sorted(missing)
        )
        raise wheel_module_completeness.WheelModuleCompletenessError(
            "installed core modules swallowed missing imports: " + detail
        )
    return modules


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
    modules = verify_installed_boot()
    print(f"installed yoke-core imports passed: {len(modules)} modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
