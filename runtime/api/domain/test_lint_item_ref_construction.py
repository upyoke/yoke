"""Tests for the item-ref-construction scanner.

The scanner flags literal item-ref prefix tokens (``f"YOK-{...}"`` construction
and ``"YOK-"`` parse/concat literals) in Python source outside the canonical
formatter/resolver and tests. The canonical helpers format from a *variable*
prefix and must not trip it.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_item_ref_construction import (
    counts_by_relpath,
    scan,
)

_PREFIXES = ["YOK", "BUZ", "PLAT"]


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_flags_fstring_construction(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/mod.py",
        'def label(item_id):\n    return f"YOK-{item_id}"\n',
    )
    hits = scan(tmp_path, _PREFIXES)
    assert len(hits) == 1
    assert hits[0].line == 2


def test_flags_parse_back_literal(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/resolve.py",
        'def to_id(ref):\n    return int(ref.replace("YOK-", ""))\n',
    )
    hits = scan(tmp_path, _PREFIXES)
    assert len(hits) == 1


def test_flags_non_yoke_prefixes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/plat.py",
        'ref = f"PLAT-{n}"\nother = "BUZ-"\n',
    )
    hits = scan(tmp_path, _PREFIXES)
    assert len(hits) == 2


def test_variable_prefix_helper_is_not_flagged(tmp_path: Path) -> None:
    # The canonical formatter builds from a variable prefix — no literal token.
    _write(
        tmp_path,
        "packages/pkg/src/fmt.py",
        'def render(prefix, seq):\n    return f"{prefix}-{seq}"\n',
    )
    assert scan(tmp_path, _PREFIXES) == []


def test_unrelated_uppercase_dashes_not_flagged(tmp_path: Path) -> None:
    # Health-check slugs and acceptance-criteria labels are not item refs.
    _write(
        tmp_path,
        "packages/pkg/src/slugs.py",
        'SLUG = "HC-obsoleted-terms"\nAC = "AC-1"\nENC = "UTF-8"\n',
    )
    assert scan(tmp_path, _PREFIXES) == []


def test_tests_and_exempt_modules_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "packages/pkg/tests/test_x.py", 'r = f"YOK-{i}"\n')
    _write(tmp_path, "packages/pkg/src/test_helper.py", 'r = f"YOK-{i}"\n')
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/project_identity.py",
        'r = f"YOK-{i}"\n',
    )
    assert scan(tmp_path, _PREFIXES) == []


def test_counts_by_relpath_aggregates(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/two.py",
        'a = f"YOK-{x}"\nb = "YOK-"\n',
    )
    hits = scan(tmp_path, _PREFIXES)
    counts = counts_by_relpath(tmp_path, hits)
    assert counts == {"packages/pkg/src/two.py": 2}


def test_no_prefixes_means_no_hits(tmp_path: Path) -> None:
    _write(tmp_path, "packages/pkg/src/mod.py", 'r = f"YOK-{i}"\n')
    assert scan(tmp_path, []) == []
