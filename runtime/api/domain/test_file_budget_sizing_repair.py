"""Focused replacement coverage for File Budget sizing repair."""

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain import idea_readiness_repair


def _entry(path: str, count: int, limit: int = DEFAULT_LIMIT) -> str:
    return (
        f"- `{path}` — current {count} lines; remaining headroom "
        f"{limit - count}; at-or-over-limit: "
        f"{str(count >= limit).lower()}; responsibility: fixture.\n"
    )


def _repair(path: str = "foo.py") -> idea_readiness_repair.RepairedPath:
    return idea_readiness_repair.RepairedPath(path, 100, 155)


def test_single_match_repairs_all_sizing_facts() -> None:
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        _entry("foo.py", 100), [_repair()], DEFAULT_LIMIT,
    )
    assert text == _entry("foo.py", 155)
    assert refused == []


def test_missing_entry_is_refused() -> None:
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        _entry("bar.py", 100), [_repair()], DEFAULT_LIMIT,
    )
    assert text == _entry("bar.py", 100)
    assert refused[0]["reason"] == "missing_file_budget_entry"


def test_duplicate_entry_is_refused() -> None:
    spec = _entry("foo.py", 100) + _entry("foo.py", 200)
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        spec, [_repair()], DEFAULT_LIMIT,
    )
    assert text == spec
    assert refused[0]["reason"] == "duplicate_count_match"
    assert refused[0]["match_count"] == 2


def test_repair_sizes_against_the_given_limit() -> None:
    text, refused = idea_readiness_repair.apply_stale_count_replacements(
        _entry("foo.py", 100, 200), [_repair()], 200,
    )
    assert text == _entry("foo.py", 155, 200)
    assert refused == []


def test_stale_issue_limit_reads_context_and_defaults_for_old_clients() -> None:
    from yoke_core.domain.idea_readiness_count_replacements import stale_issue_limit

    assert stale_issue_limit([{"context": {"limit": 200}}]) == 200
    assert stale_issue_limit([{"context": {}}]) == DEFAULT_LIMIT
    assert stale_issue_limit(
        [{"context": {"limit": 200}}, {"context": {"limit": 300}}]
    ) is None
