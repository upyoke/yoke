"""Prove a rendered Pulumi program carries every module it imports.

The rendered program is assembled from an explicit per-family file inventory,
and that inventory lives here while the modules it names live in each
consuming project's repository. A project that adds an infra module therefore
gets no local signal that a list in another repository has to change, and the
omission stays invisible until Pulumi runs the program and the import fails.

Checking the rendered directory against its own imports moves that failure to
render time, where the message can name the missing module and the inventory
that should have carried it.
"""

from __future__ import annotations

import ast
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


def assert_rendered_program_complete(
    destination: Path, *, available: Path
) -> None:
    """Refuse a render whose program imports a module it did not carry.

    ``available`` is the project's own infra directory: a bare import that
    resolves to a file there is a sibling the render owed and missed, while
    anything else is an ordinary third-party or standard-library import and
    is none of this check's business.
    """
    rendered = sorted(destination.glob("*.py"))
    carried = {path.stem for path in rendered}
    missing: dict[str, str] = {}
    for path in rendered:
        for name in _imported_module_names(path.read_text(encoding="utf-8")):
            if name in carried or name in missing:
                continue
            if (available / f"{name}.py").is_file():
                missing[name] = path.name
    if not missing:
        return
    detail = ", ".join(
        f"{name}.py (imported by {importer})"
        for name, importer in sorted(missing.items())
    )
    raise RenderedProgramIncomplete(
        "rendered Pulumi program is missing project modules it imports: "
        f"{detail}. Add each one to the matching program-file inventory in "
        "project_renderer_pulumi_files.py so the render carries it."
    )


__all__ = ["RenderedProgramIncomplete", "assert_rendered_program_complete"]
