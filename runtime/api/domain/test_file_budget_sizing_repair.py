"""Focused replacement coverage for File Budget sizing repair."""

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain import idea_readiness_repair


def _entry(path: str, count: int) -> str:
    return (
        f"- `{path}` — current {count} lines; remaining headroom "
        f"{DEFAULT_LIMIT - count}; at-or-over-limit: "
        f"{str(count >= DEFAULT_LIMIT).lower()}; responsibility: fixture.\n"
    )


def _repair(path: str = "foo.py") -> idea_readiness_repair.RepairedPath:
    return idea_readiness_repair.RepairedPath(path, 100, 155)


def test_single_match_repairs_all_sizing_facts() -> None:
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        _entry("foo.py", 100), [_repair()],
    )
    assert text == _entry("foo.py", 155)
    assert refused == []


def test_missing_entry_is_refused() -> None:
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        _entry("bar.py", 100), [_repair()],
    )
    assert text == _entry("bar.py", 100)
    assert refused[0]["reason"] == "missing_file_budget_entry"


def test_duplicate_entry_is_refused() -> None:
    spec = _entry("foo.py", 100) + _entry("foo.py", 200)
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        spec, [_repair()],
    )
    assert text == spec
    assert refused[0]["reason"] == "duplicate_count_match"
    assert refused[0]["match_count"] == 2
