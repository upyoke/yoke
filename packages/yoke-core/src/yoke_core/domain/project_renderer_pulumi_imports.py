"""Carry every project-owned sibling a rendered Pulumi program imports.

The seed inventory is per-family and lives in this repository, while the
modules a stack imports live in each consuming project's ``infra/``. A
project can add a sibling and import it without a matching inventory edit
here; materialization then used to drop that file and fail later as a
bare ``ModuleNotFoundError``. Closing the render under those imports
copies each present sibling, and a remaining miss is refused by name.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path


class RenderedProgramIncomplete(RuntimeError):
    """A rendered program imports a project module the render did not carry."""


def _imported_module_names(source: str) -> set[str]:
    """Every bare module name the source imports, however it imports it.

    Pulumi programs run with their own directory on the path, so sibling
    modules are imported by bare name — both at module scope and inside
    functions, which is where a stack defers an optional dependency.
    """
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A program that does not parse fails on its own terms with a better
        # message than anything this check could add.
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".", 1)[0])
    return names


def _missing_imported_siblings(
    destination: Path, available: Path
) -> dict[str, str]:
    """Map each missing project sibling stem to the file that imported it."""
    carried = {path.stem for path in destination.glob("*.py")}
    missing: dict[str, str] = {}
    for path in sorted(destination.glob("*.py")):
        for name in _imported_module_names(path.read_text(encoding="utf-8")):
            if name in carried or name in missing:
                continue
            if (available / f"{name}.py").is_file():
                missing[name] = path.name
    return missing


def close_rendered_program_imports(
    destination: Path, *, available: Path
) -> list[str]:
    """Copy every project-owned sibling the rendered program imports.

    Walks newly copied files so a chain of sibling imports is carried in
    one pass. Returns the filenames that were added.
    """
    added: list[str] = []
    while True:
        missing = _missing_imported_siblings(destination, available)
        if not missing:
            return added
        for name in sorted(missing):
            filename = f"{name}.py"
            shutil.copyfile(available / filename, destination / filename)
            added.append(filename)


def assert_rendered_program_complete(
    destination: Path, *, available: Path
) -> None:
    """Refuse a render whose program still imports a module it did not carry.

    ``available`` is the project's own infra directory: a bare import that
    resolves to a file there is a sibling the render owed and missed, while
    anything else is an ordinary third-party or standard-library import and
    is none of this check's business.
    """
    missing = _missing_imported_siblings(destination, available)
    if not missing:
        return
    detail = ", ".join(
        f"{name}.py (imported by {importer})"
        for name, importer in sorted(missing.items())
    )
    raise RenderedProgramIncomplete(
        "rendered Pulumi program is missing project modules it imports: "
        f"{detail}. Those files exist in the project infra tree and must "
        "be copied into the render."
    )


__all__ = [
    "RenderedProgramIncomplete",
    "assert_rendered_program_complete",
    "close_rendered_program_imports",
]
