"""Every module a rendered Pulumi program imports must also be rendered.

The set of files copied into a stack's render directory is declared
separately from the Pack manifest that ships them. A module can therefore be
added to a Pack, imported by a program in that Pack, and still be missing at
render time — the failure surfaces only as a ModuleNotFoundError during a
real `pulumi preview` against the live stack, long after the tests pass.

This walks each stack kind's declared render set and asserts it is closed
under sibling imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yoke_core.domain.pack_catalog import load_pack_descriptor, packs_root
from yoke_core.domain.project_renderer_pulumi_scoped import _stack_files

#: Packs whose infra directory supplies the rendered program files.
_SOURCE_PACKS = ("pulumi-foundation", "self-hosted-runners", "vps-hosting")


def _infra_sources() -> dict[str, Path]:
    """Map ``module.py`` to its file across every Pack's latest version."""
    found: dict[str, Path] = {}
    for slug in _SOURCE_PACKS:
        descriptor = load_pack_descriptor(slug)
        version = descriptor["latest_version"]
        infra = packs_root() / slug / "versions" / version / "files" / "infra"
        if not infra.is_dir():
            continue
        for path in infra.glob("*.py"):
            found.setdefault(path.name, path)
    return found


def _sibling_imports(path: Path) -> set[str]:
    """Return ``webapp_*`` modules a program imports at module scope.

    Only module-scope imports are checked, because only those run when the
    program loads. The stack dispatcher deliberately imports each stack's
    modules inside the function that builds that stack, so it names modules
    no single render set is ever expected to carry.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "webapp_"
        ):
            names.add(f"{node.module}.py")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("webapp_"):
                    names.add(f"{alias.name}.py")
    return names


@pytest.mark.parametrize(
    "stack_kind", ["runner-fleet", "registry", "infra", "domain", "environment"]
)
def test_rendered_stack_files_are_closed_under_sibling_imports(stack_kind):
    sources = _infra_sources()
    _template, rendered = _stack_files(stack_kind)
    declared = set(rendered)

    missing: list[str] = []
    for name in rendered:
        path = sources.get(name)
        if path is None:
            # Supplied by a Pack outside this check's source list; its own
            # imports are that Pack's concern.
            continue
        for imported in _sibling_imports(path):
            if imported not in declared and imported in sources:
                missing.append(f"{name} imports {imported}")

    assert missing == [], (
        f"{stack_kind} render set omits modules its programs import: {missing}"
    )
