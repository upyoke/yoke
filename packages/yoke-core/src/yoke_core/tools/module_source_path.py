"""Print the import origin for a Python module."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional, Sequence


def resolve_module_source_path(module_name: str) -> Optional[str]:
    """Return a module's import origin or package search root."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None
    origin = spec.origin
    if origin and origin not in {"built-in", "frozen", "namespace"}:
        return str(Path(origin).resolve())
    locations = spec.submodule_search_locations
    if locations:
        return str(Path(next(iter(locations))).resolve())
    return origin


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.module_source_path",
        description="Print the resolved import origin for a Python module.",
    )
    parser.add_argument("module_name", help="Importable module name.")
    args = parser.parse_args(argv)

    path = resolve_module_source_path(args.module_name)
    if not path:
        print(f"module not found: {args.module_name}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
