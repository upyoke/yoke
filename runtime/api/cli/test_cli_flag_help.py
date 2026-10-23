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
    name = getattr(node, "id", None) or getattr(node, "attr", None) or ""
    return name.endswith("USAGE")


def _violations() -> list[str]:
    found: list[str] = []
    for path in _parser_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            kws = _keywords(node)
            where = f"{path.relative_to(REPO)}:{node.lineno}"
            if callee in ("ArgumentParser", "add_parser"):
                if "description" in kws and _names_usage(kws["description"]):
                    found.append(f"{where} description repeats usage; use usage=")
            if callee == "add_argument" and "help" not in kws:
                if not any(kw.arg is None for kw in node.keywords):
                    found.append(f"{where} argument has no help=")
    return found


def test_every_argument_has_help_and_usage_prints_once() -> None:
    found = _violations()
    assert not found, f"{len(found)} help gap(s):\n" + "\n".join(found[:80])
