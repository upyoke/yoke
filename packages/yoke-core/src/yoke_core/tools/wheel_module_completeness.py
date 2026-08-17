"""Prove that the yoke-core wheel carries every source runtime module."""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


TEST_SUPPORT_MARKERS = (
    "_test_fixtures",
    "_test_helpers",
    "_test_schema",
    "_test_support",
)
_PACKAGE_NAME = "yoke_core"
_BUNDLE_ROOT = (_PACKAGE_NAME, "install_bundle_tree")


class WheelModuleCompletenessError(ValueError):
    """The built wheel differs from the importable source runtime."""


@dataclass(frozen=True)
class WheelModuleReport:
    """The source and wheel runtime-member sets after policy exclusions."""

    source_members: frozenset[str]
    wheel_members: frozenset[str]


def is_test_support(package: str, module: str) -> bool:
    """Return whether setuptools should omit one source-tree test helper."""
    leaf = module.rsplit(".", 1)[-1]
    return (
        ".tests" in package
        or package.endswith(".tests")
        or any(marker in leaf for marker in TEST_SUPPORT_MARKERS)
    )


def source_runtime_members(package_root: Path) -> frozenset[str]:
    """Return production Python members expected from a yoke_core source tree."""
    root = package_root.resolve()
    if root.name != _PACKAGE_NAME or not root.is_dir():
        raise WheelModuleCompletenessError(
            f"package root must be an existing {_PACKAGE_NAME} directory: {root}"
        )
    members = {_source_member(path, root) for path in root.rglob("*.py")}
    return frozenset(member for member in members if member is not None)


def wheel_runtime_members(
    wheel: Path,
) -> tuple[frozenset[str], frozenset[str]]:
    """Return production members and leaked test support from one wheel."""
    artifact = wheel.resolve()
    if not artifact.is_file():
        raise WheelModuleCompletenessError(f"wheel does not exist: {artifact}")
    with zipfile.ZipFile(artifact) as archive:
        python_members = (
            name
            for name in archive.namelist()
            if name.startswith(f"{_PACKAGE_NAME}/") and name.endswith(".py")
        )
        runtime: set[str] = set()
        leaked_support: set[str] = set()
        for member in python_members:
            classification = _classify_member(member)
            if classification == "runtime":
                runtime.add(member)
            elif classification == "test-support":
                leaked_support.add(member)
    return frozenset(runtime), frozenset(leaked_support)


def assert_wheel_module_completeness(
    package_root: Path, wheel: Path
) -> WheelModuleReport:
    """Raise unless the wheel and source production-module sets match exactly."""
    source = source_runtime_members(package_root)
    built, leaked_support = wheel_runtime_members(wheel)
    missing = sorted(source - built)
    unexpected = sorted(built - source)
    if missing or unexpected or leaked_support:
        details = []
        if missing:
            details.append("missing runtime modules: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected runtime modules: " + ", ".join(unexpected))
        if leaked_support:
            details.append(
                "source test support leaked into wheel: "
                + ", ".join(sorted(leaked_support))
            )
        raise WheelModuleCompletenessError("; ".join(details))
    return WheelModuleReport(source_members=source, wheel_members=built)


def _source_member(path: Path, package_root: Path) -> str | None:
    relative = path.relative_to(package_root.parent).as_posix()
    return relative if _classify_member(relative) == "runtime" else None


def _classify_member(member: str) -> str:
    path = PurePosixPath(member)
    parts = path.parts
    if parts[:2] == _BUNDLE_ROOT and parts != (*_BUNDLE_ROOT, "__init__.py"):
        return "bundle-payload"
    package = ".".join(parts[:-1])
    module = path.stem
    if is_test_support(package, module):
        return "test-support"
    return "runtime"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare yoke-core source runtime modules with a built wheel."
    )
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = assert_wheel_module_completeness(args.package_root, args.wheel)
    except (OSError, zipfile.BadZipFile, WheelModuleCompletenessError) as exc:
        print(f"wheel-module-completeness: {exc}")
        return 1
    print(
        "wheel runtime modules complete: "
        f"{args.wheel.name} ({len(report.wheel_members)} modules)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
