"""Unit tests for HC-tier-schema-bleed.

Tests use ``tmp_path`` plus ``monkeypatch`` of :func:`iter_tier_paths`
inside the HC module so the fixtures are fully self-contained — no live
repo paths are read and no real bleed corpus is scanned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

import pytest

from yoke_core.domain.schema_api_context_json_schemas import (
    ACCESS_PATTERN_NOTE,
    JSON_NESTED_SCHEMAS,
)
from yoke_core.engines import doctor_hc_tier_schema_bleed as mod
from yoke_core.engines.doctor_hc_tier_schema_bleed import (
    HC_SLUG,
    hc_tier_schema_bleed,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# ---------------------------------------------------------------------------
# Test fixtures and helpers.
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """The HC under test scans tier files only; it never reads *conn*."""
    return None


def _make_fixture_repo(
    tmp_path: Path, files: dict[str, str], tier_for: dict[str, int]
) -> Path:
    """Materialize fixture files under tmp_path and return the repo root.

    ``files`` maps repo-relative path -> file content. ``tier_for`` maps
    repo-relative path -> tier number (used by the ``iter_tier_paths``
    monkeypatch below).
    """

    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _install_iter(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    tier_for: dict[str, int],
) -> None:
    """Monkeypatch :func:`mod.iter_tier_paths` to yield only fixture files."""

    def fake_iter(
        repo: Path, tiers: Iterable[int] = (0, 2, 4, 5)
    ) -> Iterator[Tuple[int, Path]]:
        tier_set = set(tiers)
        for rel, tier in sorted(tier_for.items()):
            if tier not in tier_set:
                continue
            yield tier, repo_root / rel

    monkeypatch.setattr(mod, "iter_tier_paths", fake_iter)
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(repo_root))


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_tier_schema_bleed(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


# ---------------------------------------------------------------------------
# AC-6 Positives.
# ---------------------------------------------------------------------------


def test_items_worktree_path_in_tier5_fires(tmp_path, monkeypatch, conn):
    """Real table + real column outside cross-reference allow-list — WARN."""

    rel = ".agents/skills/yoke/conduct/SKILL.md"
    body = (
        "# Conduct\n\n"
        "The launcher cd's into items.worktree_path when activating.\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 5})
    _install_iter(monkeypatch, tmp_path, {rel: 5})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "items.worktree_path" in _detail(rec)
    assert HC_SLUG == rec.results[0].check_id


def test_epic_tasks_depends_on_in_tier4_fires(tmp_path, monkeypatch, conn):
    """Real table + confabulated column — WARN flagged as confabulation."""

    rel = "runtime/agents/architect.md"
    body = (
        "# Architect\n\n"
        "Inspect epic_tasks.depends_on before reassigning a task.\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 4})
    _install_iter(monkeypatch, tmp_path, {rel: 4})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "epic_tasks.depends_on" in detail
    assert "confabulation" in detail


def test_json_nested_browser_testable_in_tier5_fires(tmp_path, monkeypatch, conn):
    """Class B: ``items get YOK-N browser_testable`` — WARN names parent column."""

    rel = ".agents/skills/yoke/refine/SKILL.md"
    body = (
        "# Refine\n\n"
        "Check the flag with `db_router items get YOK-42 browser_testable`.\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 5})
    _install_iter(monkeypatch, tmp_path, {rel: 5})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "items.browser_qa_metadata" in detail
    assert ACCESS_PATTERN_NOTE in detail


# ---------------------------------------------------------------------------
# AC-6 Per-key parametrized reachability test for JSON_NESTED_SCHEMAS.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_col", list(JSON_NESTED_SCHEMAS.keys()))
def test_json_nested_schema_key_reachable(table_col):
    """Every JSON_NESTED_SCHEMAS key contributes to the HC's lookup index.

    Either the parent (table, column) appears in the lookup for at least
    one of its real nested fields, or the entry has only placeholder
    "(JSON array ...)" rows (in which case it has no top-level-key
    bleed surface and reachability via the index is irrelevant).
    """

    meta = JSON_NESTED_SCHEMAS[table_col]
    real_fields = [
        name for (name, _t, _d) in meta["fields"] if not name.startswith("(")
    ]
    if not real_fields:
        # Placeholder-only entries (e.g. epic_tasks.dependencies) are
        # documented as "the column itself is the JSON array" — Class B
        # has nothing to scan for, but the entry MUST be present in
        # JSON_NESTED_SCHEMAS so this parametrization stays exhaustive.
        return
    table, json_col = table_col
    for field in real_fields:
        parents = mod._JSON_FIELD_INDEX.get(field, [])
        assert (table, json_col) in parents, (
            f"{table_col} nested field {field!r} not reachable in HC index"
        )


# ---------------------------------------------------------------------------
# AC-6 Negatives — cross-reference allow-list.
# ---------------------------------------------------------------------------


def test_see_your_items_packet_stanza_passes(tmp_path, monkeypatch, conn):
    """`see your `items` packet stanza` is the sanctioned cite-toward shape."""

    rel = "AGENTS.md"
    body = "Worktree records on item rows — see your `items` packet stanza.\n"
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 0})
    _install_iter(monkeypatch, tmp_path, {rel: 0})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_see_the_worktree_column_packet_stanza_passes(tmp_path, monkeypatch, conn):
    """`see the `worktree` column in your `items` packet stanza` passes."""

    rel = ".yoke/docs/commands.md"
    body = (
        "The worktree binding is recorded — see the `worktree` column in "
        "your `items` packet stanza.\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 2})
    _install_iter(monkeypatch, tmp_path, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


# ---------------------------------------------------------------------------
# AC-6 Edges — archive exemption, empty file, fenced code block.
# ---------------------------------------------------------------------------


def test_archive_path_does_not_fire(tmp_path, monkeypatch, conn):
    """Files under docs/archive/ are exempt regardless of bleed content."""

    rel = "docs/archive/teaching-tier-discipline-audit.md"
    body = "# Audit\n\nHistorical: items.worktree_path used to drift here.\n"
    _make_fixture_repo(tmp_path, {rel: body}, {})
    # The iter_tier_paths monkeypatch yields nothing — archive paths are
    # not yielded for tiers 0/2/4/5 by the real iterator either. The HC
    # treats the resulting empty scan as PASS.
    _install_iter(monkeypatch, tmp_path, {})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_empty_file_emits_pass(tmp_path, monkeypatch, conn):
    rel = "docs/OVERVIEW.md"
    _make_fixture_repo(tmp_path, {rel: ""}, {rel: 2})
    _install_iter(monkeypatch, tmp_path, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_fenced_sql_block_does_not_fire(tmp_path, monkeypatch, conn):
    """Fenced code blocks are exempt for Class A (raw SQL examples)."""

    rel = ".yoke/docs/commands.md"
    body = (
        "# Commands\n\n"
        "Example:\n\n"
        "```sql\n"
        "SELECT items.id FROM items;\n"
        "```\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 2})
    _install_iter(monkeypatch, tmp_path, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_fenced_block_still_fires_class_b(tmp_path, monkeypatch, conn):
    """Class B applies inside fences too — a fenced ``items get`` example
    with a nested-field shape is still wrong teaching."""

    rel = ".yoke/docs/commands.md"
    body = (
        "# Commands\n\n"
        "```bash\n"
        "db_router items get YOK-42 browser_testable\n"
        "```\n"
    )
    _make_fixture_repo(tmp_path, {rel: body}, {rel: 2})
    _install_iter(monkeypatch, tmp_path, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "items.browser_qa_metadata" in _detail(rec)


# ---------------------------------------------------------------------------
# AC-8 self-skip — unresolvable repo root.
# ---------------------------------------------------------------------------


def test_self_skip_when_repo_root_unresolvable(monkeypatch, conn):
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()


# ---------------------------------------------------------------------------
# Truncation budget — ≤40 findings + "N more" suffix.
# ---------------------------------------------------------------------------


def test_findings_truncated_to_budget(tmp_path, monkeypatch, conn):
    """A bleed-heavy file is truncated to <=40 entries with a tail summary."""

    # 50 bleed lines on a single file — half the budget over the cap.
    body_lines: List[str] = ["# Heavy\n"]
    for i in range(50):
        body_lines.append(f"line {i}: items.worktree_path is the binding.\n")
    rel = "runtime/agents/engineer.md"
    _make_fixture_repo(tmp_path, {rel: "".join(body_lines)}, {rel: 4})
    _install_iter(monkeypatch, tmp_path, {rel: 4})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "more references" in detail
    # The truncated section is 40 finding lines + 1 summary line; only
    # the 40 finding lines start with "- ".
    finding_lines = [ln for ln in detail.splitlines() if ln.startswith("- ")]
    assert len(finding_lines) == 40
