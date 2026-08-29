"""Source-tree evidence that a vocabulary value is still produced.

Split from ``check_unreachable_vocabulary_value`` so the scanner and the check
that consumes it stay separately readable. Underscore-prefixed on purpose:
discovery imports ``check_*.py`` only, so this is a helper the check shares
rather than a check itself.

Everything here answers one question — where, in live source, does a value
appear, and is that appearance a producer or only a comparison? Nothing here
decides whether a value is dead; the check pairs these answers with stored-row
evidence before it concludes anything.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Set, Tuple

from yoke_core.engines.doctor_obsoleted_scan_scope import SCAN_DIRS_BY_EXT
from yoke_core.engines.doctor_tree_scan import iter_tree_files

#: Source roots are the ones the obsoleted-term scan already resolves for
#: Python; the web assets that write these same values live under them too.
_CODE_ROOTS: Tuple[str, ...] = SCAN_DIRS_BY_EXT[".py"]
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs")

#: Trees that hold no live writer. Migrations are permanent ordered history
#: rather than a live path — and a migration that really did write a value
#: leaves rows behind, which clears it through the row evidence instead.
_EXCLUDED_PARTS = frozenset(
    {"tests", "fixtures", "build", "dist", "node_modules", "__pycache__",
     "migrations"}
)

_DDL_MARKERS = ("CHECK(", "CHECK (")


def _alternation(terms: Set[str], template: str) -> Optional[Any]:
    """Compile one pattern over every term, or nothing when there are none.

    One combined pattern rather than one per term: this scan crosses several
    thousand files, and a per-term pass over each of them is the difference
    between a check that runs in seconds and one nobody waits for.
    """
    if not terms:
        return None
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(template % "|".join(re.escape(t) for t in ordered))


def _is_live_source(relative: Path) -> bool:
    """Judge a repo-relative path, never an absolute one.

    A lane worktree sits under ``.worktrees/<branch>/``, so matching excluded
    names against absolute parts would discard every file the scan is for.
    """
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return False
    name = relative.name
    return not (
        name.startswith("test_")
        or "_test." in name
        or ".test." in name
        or name == "conftest.py"
    )


def _iter_source(repo_root: Path) -> Iterator[Tuple[Path, str]]:
    for rel in _CODE_ROOTS:
        base = repo_root / rel
        if not base.is_dir():
            continue
        for path in iter_tree_files(base, prune_dir_names=_EXCLUDED_PARTS):
            if path.suffix not in _CODE_SUFFIXES:
                continue
            try:
                relative = path.relative_to(repo_root)
            except ValueError:
                continue
            if not _is_live_source(relative):
                continue
            try:
                yield path.read_text(encoding="utf-8", errors="replace"), str(
                    relative
                )
            except OSError:
                continue


def _declaration_sites(
    tree: ast.Module, values: Set[str]
) -> Tuple[Set[int], Set[int], Dict[str, int]]:
    """Return the module's declaration nodes, declaration lines, and origins.

    A constant's binding site, and the collection literal gathering those
    constants into a vocabulary, are where a value is *declared*. Declaring is
    not producing, so both are held out of the evidence scan and reported
    instead as where the surviving definition lives.
    """
    constants: Dict[str, str] = {}
    nodes: Set[int] = set()
    lines: Set[int] = set()
    origins: Dict[str, int] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.targets[0].id] = node.value.value
            nodes.add(id(node.value))
            lines.add(node.lineno)
            if node.value.value in values:
                origins.setdefault(node.value.value, node.lineno)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        collection = node.value
        if not isinstance(collection, (ast.Tuple, ast.List, ast.Set)):
            continue
        elements = collection.elts
        if not elements or not all(
            (isinstance(e, ast.Name) and e.id in constants)
            or (isinstance(e, ast.Constant) and isinstance(e.value, str))
            for e in elements
        ):
            continue
        for element in elements:
            nodes.add(id(element))
            lines.add(element.lineno)
    return nodes, lines, origins


def vocabulary_constants(
    repo_root: Path, values: Set[str], quoted: Any
) -> Dict[str, Set[str]]:
    """Map every module-level constant name bound to a vocabulary value.

    Collected across the whole tree before any use is classified, because the
    module that *defines* a vocabulary constant is rarely the one that writes
    it — the writer imports the name. A map built per module would read an
    imported constant as an unknown name and miss the writer entirely.
    """
    named: Dict[str, Set[str]] = {}
    for text, relative in _iter_source(repo_root):
        if not relative.endswith(".py") or not quoted.search(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and node.value.value in values
            ):
                named.setdefault(node.targets[0].id, set()).add(node.value.value)
    return named


def _scan_python(
    text: str,
    values: Set[str],
    aliases: Dict[str, Set[str]],
    relative: str,
    evidence: Dict[str, list],
) -> Set[int]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    nodes, lines, origins = _declaration_sites(tree, values)
    for value, lineno in origins.items():
        evidence["declared"].append((value, f"{relative}:{lineno}"))
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for node in ast.walk(tree):
        if id(node) in nodes:
            continue
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        bound = aliases.get(node.id)
        if not bound:
            continue
        kind = (
            "compared"
            if isinstance(parents.get(id(node)), (ast.Compare, ast.MatchValue))
            else "produced"
        )
        for value in bound:
            evidence[kind].append((value, f"{relative}:{node.lineno}"))
    return lines


def source_evidence(repo_root: Path, values: Set[str]) -> Dict[str, list]:
    """Return declaration, production, comparison, and mention sites by value."""
    evidence: Dict[str, list] = {
        "declared": [], "produced": [], "compared": [], "mentioned": []
    }
    quoted = _alternation(values, "['\"](%s)['\"]")
    if quoted is None:
        return evidence
    aliases = vocabulary_constants(repo_root, values, quoted)
    names = _alternation(set(aliases), r"\b(%s)\b")
    for text, relative in _iter_source(repo_root):
        mentions = {match.group(1) for match in quoted.finditer(text)}
        named = names is not None and names.search(text) is not None
        if not mentions and not named:
            continue
        for value in mentions:
            evidence["mentioned"].append((value, relative))
        declared_lines: Set[int] = set()
        if relative.endswith(".py"):
            declared_lines = _scan_python(
                text, values, aliases, relative, evidence
            )
        if not mentions:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if number in declared_lines:
                continue
            if any(marker in line for marker in _DDL_MARKERS):
                continue
            for match in quoted.finditer(line):
                evidence["produced"].append(
                    (match.group(1), f"{relative}:{number}")
                )
    return evidence


__all__ = ["source_evidence", "vocabulary_constants"]
