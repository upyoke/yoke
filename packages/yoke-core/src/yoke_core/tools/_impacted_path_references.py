"""Paths a source file names, and the modules those paths resolve to.

Sibling of :mod:`yoke_core.tools._impacted_import_index`, which owns the
reverse import graph and folds these edges into it. Split out to keep
both files under the authored-file line cap.

A file names another file by path in two shapes, and neither one is an
import. It writes the whole repo-relative path down as a literal —
``"pkg/governed.py"``, how a contract roster names its subjects — or it
assembles the path a segment at a time, ``ROOT / "packaging" /
"public-installer" / "install.py"``, how a test names a script it loads
from disk. The assembled shape writes no complete path anywhere, so
reading only the string constants leaves the bare file name, and a bare
name that three files in this repository carry resolves to nothing.
That is a real test of the public installer going unselected until CI
found the missed assertion, which is why the composition is read here as
the path it spells out.
"""

from __future__ import annotations

import ast
import re

#: A path to a Python file is a dependency reference. A bare file name
#: counts too, resolved only when it is unambiguous, so a lone
#: ``conftest.py`` links to nothing while ``pkg/conftest.py`` links to
#: the one file it names.
_REPO_RELATIVE_PY = re.compile(r"^[\w.\-/]+\.py$")

#: Longest literal worth reading as a path; beyond this it is prose.
_MAX_LENGTH = 200


def named_path_references(tree: ast.AST) -> set[str]:
    """Every ``.py`` path *tree* names, written whole or composed.

    Resolved against the index's own file list by
    :func:`resolve_named_path`, so a path naming no real file is simply
    dropped rather than becoming an inert key.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            named = _path_shaped(node.value if isinstance(node.value, str) else "")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            segments = _constant_tail(node)
            # One segment is the bare name the literal branch already
            # reads; composition earns its keep from two or more.
            named = _path_shaped("/".join(segments)) if len(segments) > 1 else None
        else:
            continue
        if named:
            found.add(named)
    return found


def resolve_named_path(
    named: str,
    module_of: dict[str, str],
    by_file_name: dict[str, set[str]],
) -> "str | None":
    """The module one named path resolves to, or ``None`` for none.

    An exact repo-relative path answers directly. Anything else must
    name a single file to resolve: a composed path is matched as a whole
    trailing path — every segment of it, not its basename and not its
    parent directory — and a bare name resolves only when exactly one
    file in the repository carries it. The common ambiguous names,
    ``__init__.py`` and ``conftest.py``, would otherwise link one
    reference to every package in the tree, which is a widening rather
    than a reference.
    """
    module = module_of.get(named)
    if module is not None:
        return module
    candidates = by_file_name.get(named.rsplit("/", 1)[-1], set())
    if "/" in named:
        suffix = f"/{named}"
        candidates = {rel for rel in candidates if rel.endswith(suffix)}
    if len(candidates) != 1:
        return None
    return module_of.get(next(iter(candidates)))


def _constant_tail(node: ast.BinOp) -> tuple[str, ...]:
    """Trailing segments of a ``/`` chain that can be read statically.

    The walk stops at the first operand it cannot read — the anchor a
    composition hangs from (``Path(__file__).resolve().parents[3]``) and
    any dynamic segment alike — and keeps only what follows it. So a
    chain rooted at a repository anchor yields the repo-relative path it
    spells, while ``root / chosen_dir / "install.py"`` yields the bare
    name alone and stays as ambiguous as it reads.
    """
    segments: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        value = _segment(current.right)
        if value is None:
            return tuple(reversed(segments))
        segments.append(value)
        current = current.left
    anchor = _segment(current)
    if anchor is not None:
        segments.append(anchor)
    return tuple(reversed(segments))


def _segment(node: ast.expr) -> "str | None":
    """One readable path segment: a string, or a path built from one.

    ``Path("/usr/local/share")`` anchors its composition somewhere this
    repository never is, and reading it is what keeps the segments after
    it from resolving against a repository path they merely end with.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        argument = node.args[0]
        if name.endswith("Path") and isinstance(argument, ast.Constant):
            return argument.value if isinstance(argument.value, str) else None
    return None


def _path_shaped(value: str) -> "str | None":
    stripped = value.strip()
    if len(stripped) > _MAX_LENGTH or not _REPO_RELATIVE_PY.match(stripped):
        return None
    return stripped


__all__ = ["named_path_references", "resolve_named_path"]
