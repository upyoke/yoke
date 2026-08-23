"""Tests for the item-ref-construction scanner.

The scanner flags literal item-ref prefix tokens (``f"YOK-{...}"`` construction
and ``"YOK-"`` parse/concat literals) in Python source outside the canonical
formatter/resolver and tests. The canonical helpers format from a *variable*
prefix and must not trip it.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_item_ref_bare_cli_token import (
    scan_bare_internal_cli_token,
)
from yoke_core.domain.lint_item_ref_construction import (
    counts_by_relpath,
    scan,
    scan_parser_policy,
    stale_parser_policy_allowances,
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


def test_flags_implicit_internal_opt_out(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/parse.py",
        "parse_item_id(raw, allow_bare_internal=True)\n",
    )
    hits = scan_parser_policy(tmp_path)
    assert [(hit.path.name, hit.line) for hit in hits] == [("parse.py", 1)]


def test_flags_project_blind_prefix_regex(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/parse.py",
        'PREFIX = re.compile(r"^[Yy][Oo][Kk]-")\n',
    )
    assert len(scan_parser_policy(tmp_path)) == 1


def test_flags_optional_project_blind_prefix_regex(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/parse.py",
        'REF = re.compile(r"^(?:[Yy][Oo][Kk]-)?([0-9]+)$")\n',
    )
    assert len(scan_parser_policy(tmp_path)) == 1


def test_flags_generic_prefix_tail_parser(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/parse.py",
        'REF = re.compile(r"^[A-Za-z][A-Za-z0-9]*-0*(\\d+)$")\n',
    )
    assert len(scan_parser_policy(tmp_path)) == 1


def test_flags_numeric_tail_item_ref_coercion(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/parse.py",
        'item_id = int(raw.rsplit("-", 1)[-1])\n',
    )
    hits = scan_parser_policy(tmp_path)
    assert [(hit.path.name, hit.line) for hit in hits] == [("parse.py", 1)]


def test_numeric_tail_allowances_are_exact_and_stale_checked(
    tmp_path: Path,
) -> None:
    allowed = (
        "packages/yoke-core/src/yoke_core/domain/item_ref_columns.py"
    )
    _write(
        tmp_path,
        allowed,
        'tail = raw.rsplit("-", 1)[-1]\n'
        'parse_item_id(raw, allow_bare_internal=True)\n',
    )

    assert scan_parser_policy(tmp_path) == []
    stale = stale_parser_policy_allowances(tmp_path)
    assert allowed not in stale
    assert len(stale) == 1


def test_baseline_counts_matches_classified_entries() -> None:
    from yoke_core.domain.item_ref_construction_baseline import (
        BASELINE,
        baseline_count,
        baseline_counts,
    )

    for path, entry in BASELINE.items():
        assert baseline_count(path) == int(entry["count"])
        assert isinstance(entry["reason"], str)
        assert isinstance(entry["note"], str)
    assert baseline_counts() == {
        path: int(entry["count"]) for path, entry in BASELINE.items()
    }


def test_repository_item_ref_policy_has_no_stale_allowances() -> None:
    from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX
    from yoke_core.domain.item_ref_construction_baseline import baseline_counts

    root = Path(__file__).resolve().parents[3]
    counts = counts_by_relpath(root, scan(root, [DEFAULT_PUBLIC_ITEM_PREFIX]))
    allowed = baseline_counts()
    offenders = {
        path: count
        for path, count in counts.items()
        if count > allowed.get(path, 0)
    }
    stale = {
        path: (counts.get(path, 0), count)
        for path, count in allowed.items()
        if counts.get(path, 0) < count
    }
    policy = [
        (str(hit.path.relative_to(root)), hit.line, hit.snippet)
        for hit in scan_parser_policy(root)
    ]
    stale_policy = stale_parser_policy_allowances(root)
    cli_hits = [
        (str(hit.path.relative_to(root)), hit.line, hit.snippet)
        for hit in scan_bare_internal_cli_token(root)
    ]
    assert (offenders, stale, policy, stale_policy, cli_hits) == (
        {}, {}, [], [], [],
    )


def test_flags_bare_id_items_update_token(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/pipe.py",
        '_yoke_db("items", "update", item_id, "deploy_stage", stage)\n',
    )
    hits = scan_bare_internal_cli_token(tmp_path)
    assert len(hits) == 1
    assert hits[0].line == 1


def test_flags_str_item_id_done_sync(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/sync.py",
        "sync_done_item(str(item_id), old_status)\n",
    )
    hits = scan_bare_internal_cli_token(tmp_path)
    assert len(hits) == 1


def test_rendered_item_ref_cli_token_is_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/pkg/src/ok.py",
        '_yoke_db("items", "get", item_ref, "deploy_stage")\n',
    )
    assert scan_bare_internal_cli_token(tmp_path) == []
