"""Package-split codemod engine for the transitional package carve-out.

Given a rename map {old_dotted_module: new_dotted_module}, this rewrites every
dotted reference across the chosen file set and (in apply mode) `git mv`s the
physical source files to their new package homes. It is the scripted instrument that
executes the moves; it does NOT decide the rules — those are frozen in `rules.py`.

Reference forms rewritten (longest-old-prefix-first so a more specific rename wins):
- `from <old>[.sub] import ...`        -> `from <new>[.sub] import ...`
- `import <old>[.sub]`/`... as x`      -> `import <new>[.sub]`/`... as x`
- bare/quoted dotted-path string refs  -> rewritten in place (dispatch tables, docs,
                                          `python3 -m <old>` invocations, `-m <old>`)

A reference matches `<old>` only at a dotted-identifier boundary (it will not rewrite
`runtime.api.domainfoo` when renaming `runtime.api.domain`), so prefix renames are
safe. Physical 1:1 moves are derived from the new dotted path; consolidations
(several old modules -> one new file) are marked in `rules.py` and handled by hand —
the engine only rewrites their references, never invents a merge.

Usage:
  python3 packages/_codemod/apply.py --slice contracts --dry-run
  python3 packages/_codemod/apply.py --slice contracts --apply
  python3 packages/_codemod/apply.py --only runtime.api.domain.field_note_text --apply
"""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# Import the frozen rules sitting alongside this engine.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules as _rules  # noqa: E402

# File suffixes whose dotted references the codemod rewrites.
CODE_SUFFIXES = {".py"}
TEXT_SUFFIXES = {".md", ".json", ".toml", ".txt", ".cfg", ".ini"}

# Directories never touched. docs/archive (incl. the move-map) is the
# HISTORICAL record and intentionally keeps the old dotted paths it documents.
EXCLUDE_DIR_PARTS = {
    ".git",
    ".worktrees",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}
EXCLUDE_PREFIXES = (
    "packages/_codemod/",
    "docs/archive/",
)


def _dotted_to_path(new_dotted: str) -> str:
    """yoke_contracts.api.function_call -> packages/yoke-contracts/src/yoke_contracts/api/function_call.py"""
    top = new_dotted.split(".")[0]
    pkg = "packages/" + top.replace("_", "-") + "/src/"
    return pkg + new_dotted.replace(".", "/") + ".py"


def _old_dotted_to_path(old_dotted: str) -> str:
    """runtime.api.domain.foo -> runtime/api/domain/foo.py (runtime is at the repo root)."""
    return old_dotted.replace(".", "/") + ".py"


@functools.lru_cache(maxsize=None)
def _ref_pattern(old: str) -> re.Pattern:
    """Match `old` only at a dotted-identifier boundary (not mid-identifier).

    Cached: the core bulk rename reuses each of ~2,700 patterns across ~3,000 files,
    so compiling once per unique `old` (not once per file×rename) is the dominant win."""
    esc = re.escape(old)
    # (?<![\w.]) : not preceded by an identifier char or a dot (so we match the
    #              whole dotted root, never a suffix of a longer module path).
    # (?![\w])   : the matched root is not immediately continued by an identifier
    #              char; a following '.' (submodule) IS allowed and left intact.
    return re.compile(r"(?<![\w.])" + esc + r"(?![\w])")


def iter_files(repo_root: Path, suffixes: set) -> Iterable[Path]:
    for p in repo_root.rglob("*"):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        rel = p.relative_to(repo_root).as_posix()
        if any(part in EXCLUDE_DIR_PARTS for part in p.relative_to(repo_root).parts):
            continue
        if any(rel.startswith(pref) for pref in EXCLUDE_PREFIXES):
            continue
        yield p


@functools.lru_cache(maxsize=None)
def _from_parent_pattern(old_parent: str, old_leaf: str) -> re.Pattern:
    """Match a single-name `from <old_parent> import <old_leaf>[ as alias][ # c]` line."""
    return re.compile(
        r"(?m)^(?P<indent>[ \t]*)from " + re.escape(old_parent) + r" import "
        + re.escape(old_leaf)
        + r"(?P<alias>(?:[ \t]+as[ \t]+\w+)?)(?P<tail>[ \t]*(?:#.*)?)$"
    )


@functools.lru_cache(maxsize=None)
def _multi_from_parent_pattern(old_parent: str, old_leaf: str) -> re.Pattern:
    """Detect a multi-name `from <old_parent> import ... <old_leaf> ...` (incl. paren
    groups) so the engine can REPORT it for manual splitting rather than mis-rewrite."""
    return re.compile(
        r"from " + re.escape(old_parent) + r" import\b[^\n]*\b" + re.escape(old_leaf) + r"\b"
    )


def rewrite_text(text: str, renames: List[Tuple[str, str]]) -> Tuple[str, int, List[str]]:
    """Apply renames longest-old-first; return (new_text, substitutions, warnings).

    Two passes per rename: (1) the full dotted reference (`from old import`,
    `import old`, quoted strings, `-m old`); (2) the `from <parent> import <leaf>`
    submodule form, where the leaf is the relocated module. When the leaf name
    changes in the move, the binding is preserved with `as <old_leaf>`. Multi-name
    `from parent import a, b` lines are detected and reported, never auto-rewritten
    (splitting them safely needs human judgement)."""
    total = 0
    warnings: List[str] = []
    for old, new in sorted(renames, key=lambda kv: len(kv[0]), reverse=True):
        # Substring pre-filter: `old` must be a literal substring for the dotted-ref
        # regex to match. Skipping the scan when it is absent is output-identical and
        # prunes the vast majority of file×rename pairs in the core bulk rename.
        if old in text:
            text, n = _ref_pattern(old).subn(new, text)
            total += n
        if "." not in old or "." not in new:
            continue
        old_parent, old_leaf = old.rsplit(".", 1)
        # `from <old_parent> import <old_leaf>` needs both fragments present (they are
        # not contiguous, so the pass-1 `old` check above does not cover this form).
        if old_parent not in text or old_leaf not in text:
            continue
        new_parent, new_leaf = new.rsplit(".", 1)

        def _repl(m: "re.Match") -> str:
            alias = m.group("alias")
            tail = m.group("tail")
            indent = m.group("indent")
            if alias or new_leaf == old_leaf:
                return f"{indent}from {new_parent} import {new_leaf}{alias}{tail}"
            # no explicit alias + leaf renamed -> preserve the local binding name.
            return f"{indent}from {new_parent} import {new_leaf} as {old_leaf}{tail}"

        text, n2 = _from_parent_pattern(old_parent, old_leaf).subn(_repl, text)
        total += n2
        # Anything still matching the multi-name detector after the single-name pass
        # is an un-rewritten multi-import that needs manual splitting.
        if _multi_from_parent_pattern(old_parent, old_leaf).search(text):
            warnings.append(
                f"multi-name `from {old_parent} import ... {old_leaf} ...` "
                f"needs manual split (leaf -> {new})"
            )
    return text, total, warnings


def physical_moves(renames: Dict[str, str]) -> List[Tuple[str, str]]:
    """1:1 source moves implied by the rename map, skipping consolidations and
    package __init__.py files. A package `__init__.py` move would collide with the
    empty init the engine auto-creates along every other module's destination path,
    and a non-empty one carries re-exports that must be content-merged by hand."""
    moves = []
    consolidated_targets = _rules.CONSOLIDATED_NEW_MODULES
    for old, new in renames.items():
        if new in consolidated_targets:
            continue  # hand-merged; engine only rewrites references
        src = _old_dotted_to_path(old)
        if src.endswith("/__init__.py"):
            continue  # package init: content-merged by hand, never auto-moved
        dst = _dotted_to_path(new)
        moves.append((src, dst))
    return moves


def core_renames(repo_root: Path) -> Dict[str, str]:
    """Core bulk rename map: every runtime/api/** module (and package) that
    resolves to yoke_core.* via the frozen rules. Core is the default sink, so the
    cli-destined domain modules resolve here too and are carved to yoke_cli by a
    later step; the runtime.api.cli.* UX modules resolve to None and stay in place.
    Package entries (e.g. runtime.api.domain) rewrite bare-package imports safely
    because every submodule is also in the map and rewritten first (longest-first)."""
    renames: Dict[str, str] = {}
    api_root = repo_root / "runtime" / "api"
    for p in api_root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        # Tests + conftest stay at runtime/api/ under the runtime/api/conftest.py
        # fixture umbrella + testpaths; only source relocates. They import the moved
        # source by its new yoke_core.* name (rewritten in place). The final test
        # relocation + conftest restructure happens in a later step.
        if p.name.startswith("test_") or p.name == "conftest.py":
            continue
        rel = p.relative_to(repo_root).as_posix()
        dotted = rel[: -len(".py")].replace("/", ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]  # the package module itself
        new = _rules.resolve(dotted)
        if new is None or not new.startswith("yoke_core"):
            continue
        renames[dotted] = new
    return renames


def run(repo_root: Path, renames: Dict[str, str], apply: bool) -> int:
    rename_pairs = list(renames.items())
    touched = 0
    subs = 0
    all_warnings: List[str] = []
    for f in iter_files(repo_root, CODE_SUFFIXES | TEXT_SUFFIXES):
        original = f.read_text(encoding="utf-8")
        new_text, n, warns = rewrite_text(original, rename_pairs)
        if warns:
            rel = f.relative_to(repo_root).as_posix()
            all_warnings.extend(f"  WARN {rel}: {w}" for w in warns)
        if n:
            touched += 1
            subs += n
            if apply:
                f.write_text(new_text, encoding="utf-8")
    print(f"references: {subs} substitutions across {touched} files "
          f"({'APPLIED' if apply else 'dry-run'})")
    if all_warnings:
        print(f"manual-review needed ({len(all_warnings)} multi-name imports):")
        for w in all_warnings:
            print(w)

    moves = physical_moves(renames)
    moved = 0
    for src, dst in moves:
        src_p = repo_root / src
        if not src_p.exists():
            print(f"  SKIP move (missing source): {src}")
            continue
        dst_p = repo_root / dst
        if apply:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            # ensure package __init__.py exists along the new path
            _ensure_pkg_inits(repo_root, dst_p)
            subprocess.run(["git", "-C", str(repo_root), "mv", src, dst], check=True)
        moved += 1
        if not apply:
            print(f"  move: {src} -> {dst}")
    print(f"moves: {moved} 1:1 source moves ({'APPLIED' if apply else 'dry-run'})")
    return 0


def _ensure_pkg_inits(repo_root: Path, dst_file: Path) -> None:
    """Create empty __init__.py for any new package dir between src root and dst."""
    parts = dst_file.relative_to(repo_root).parts
    try:
        src_idx = parts.index("src")
    except ValueError:
        return
    cur = repo_root.joinpath(*parts[: src_idx + 1])
    for part in parts[src_idx + 1 : -1]:
        cur = cur / part
        init = cur / "__init__.py"
        if not init.exists():
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_text("", encoding="utf-8")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Package-split codemod")
    ap.add_argument("--slice", help="named slice from rules.SLICES")
    ap.add_argument("--only", help="single old dotted module to move")
    ap.add_argument("--core", action="store_true",
                    help="core bulk: every runtime/api/** resolving to yoke_core.*")
    ap.add_argument("--repo-root", default=None, help="defaults to git toplevel")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip()
    )

    if args.only:
        renames = {args.only: _rules.resolve(args.only)}
        if renames[args.only] is None:
            print(f"no rule for {args.only}", file=sys.stderr)
            return 2
    elif args.core:
        renames = core_renames(repo_root)
    elif args.slice:
        renames = _rules.slice_renames(args.slice)
    else:
        ap.error("pass --core, --slice, or --only")
        return 2

    return run(repo_root, renames, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
