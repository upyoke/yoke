"""``yoke`` help pages explain every argument and print usage once.

A parser whose ``description`` repeats its usage string prints the usage
twice; set ``usage=`` instead. An argument without ``help=`` shows only its
name. Both checks read the source of every module that builds a ``yoke``
parser.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI_ROOT = REPO / "packages" / "yoke-cli" / "src" / "yoke_cli"
PARSER_MODULE_ROOTS = (
    REPO / "packages" / "yoke-core" / "src",
    REPO / "packages" / "yoke-harness" / "src",
)


def _parser_modules() -> list[Path]:
    modules = sorted(CLI_ROOT.rglob("*.py"))
    for root in PARSER_MODULE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "ArgumentParser(" in text and 'prog="yoke ' in text:
                modules.append(path)
    return modules


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _names_usage(node: ast.expr) -> bool:
    """A description built from a usage string (``X_USAGE``, ``usage``)."""
    for part in ast.walk(node):
        name = getattr(part, "id", None) or getattr(part, "attr", None) or ""
        if name.upper().endswith("USAGE") and not name.endswith("_parser"):
            return True
    return False


def _add_argument_aliases(tree: ast.AST) -> set[str]:
    """Local names bound to ``parser.add_argument`` (``add = p.add_argument``)."""
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and getattr(node.value, "attr", None) == "add_argument"
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _violations() -> list[str]:
    found: list[str] = []
    for path in _parser_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        adders = {"add_argument", *_add_argument_aliases(tree)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            kws = _keywords(node)
            where = f"{path.relative_to(REPO)}:{node.lineno}"
            if callee in ("ArgumentParser", "add_parser"):
                if "description" in kws and _names_usage(kws["description"]):
                    found.append(f"{where} description repeats usage; use usage=")
            if callee in adders and "help" not in kws:
                if not any(kw.arg is None for kw in node.keywords):
                    found.append(f"{where} argument has no help=")
    return found


def test_every_argument_has_help_and_usage_prints_once() -> None:
    found = _violations()
    assert not found, f"{len(found)} help gap(s):\n" + "\n".join(found[:80])
