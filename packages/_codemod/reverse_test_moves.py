"""Reverse the core codemod's test/conftest moves (transitional helper).

The `--core` bulk move swept every `runtime/api/**/test_*.py` and `conftest.py` into
`packages/yoke-core/src/yoke_core/**` alongside the source it moved. That breaks the
test suite: `testpaths = ["runtime/api", "tests"]` no longer collects them, and they fall
out from under the `runtime/api/conftest.py` fixture umbrella (`pytest_plugins` + shared
fixtures). The established convention is that **tests stay at `runtime/api/`** and
import the relocated source by its new `yoke_core.*` name; relocating the tests and
restructuring the conftest is deferred until later.

This script git-mv's every moved test/conftest back to its git-recorded original
`runtime/api/` location (content — the already-rewritten `yoke_core.*` imports — is
preserved). Run once, as a single Python process so the git-mv subprocesses move with the
codemod's own path-claim posture rather than per-call Bash guarding.

  python3 packages/_codemod/reverse_test_moves.py            # apply
  python3 packages/_codemod/reverse_test_moves.py --dry-run  # preview
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply as _apply  # noqa: E402
import rules as _rules  # noqa: E402

_TEST_LEAF = re.compile(r"(?:^|/)(?:test_[^/]+\.py|conftest\.py)$")


def _repo_root() -> Path:
    return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip())


def _staged_renames(root: Path) -> list[tuple[str, str]]:
    """(old, new) for every staged rename, using permissive rename detection so a
    test file whose imports were rewritten in the same move is still paired."""
    out = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--cached", "-M05", "--name-status"]
    ).decode()
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts and parts[0].startswith("R") and len(parts) == 3:
            pairs.append((parts[1], parts[2]))
    return pairs


def _ref_reversal_map(root: Path) -> dict[str, str]:
    """Inverse rename map for every test/conftest now back at runtime/api/: the codemod
    rewrote references to these modules to their yoke_core.* name, but the FILE moved
    back, so any importer (conftest, shared test helpers, base classes) is now broken.
    Map yoke_core.* (the codemod's target) -> runtime.api.* (the restored home)."""
    inverse: dict[str, str] = {}
    api_root = root / "runtime" / "api"
    for p in api_root.rglob("*.py"):
        if "__pycache__" in p.parts or not _TEST_LEAF.search(p.as_posix()):
            continue
        old_dotted = p.relative_to(root).as_posix()[: -len(".py")].replace("/", ".")
        new_dotted = _rules.resolve(old_dotted)
        if new_dotted and new_dotted != old_dotted:
            inverse[new_dotted] = old_dotted
    return inverse


def main(argv: list[str]) -> int:
    apply = "--dry-run" not in argv
    root = _repo_root()
    moved = 0
    for old, new in _staged_renames(root):
        # Only reverse test/conftest files whose ORIGINAL home was runtime/api/.
        if not old.startswith("runtime/api/") or not _TEST_LEAF.search(old):
            continue
        if not new.startswith("packages/yoke-core/src/"):
            continue
        if apply:
            (root / old).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(root), "mv", new, old], check=True)
        moved += 1
        print(f"  {new} -> {old}")
    print(f"reversed {moved} test/conftest moves ({'APPLIED' if apply else 'dry-run'})")

    # Second pass: reverse references to the moved-back test/conftest modules.
    inverse = _ref_reversal_map(root)
    pairs = list(inverse.items())
    subs = 0
    for f in _apply.iter_files(root, _apply.CODE_SUFFIXES | _apply.TEXT_SUFFIXES):
        text = f.read_text(encoding="utf-8")
        new_text, n, _ = _apply.rewrite_text(text, pairs)
        if n and apply:
            f.write_text(new_text, encoding="utf-8")
        subs += n
    print(f"reversed {subs} test-module references across the tree "
          f"({'APPLIED' if apply else 'dry-run'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
