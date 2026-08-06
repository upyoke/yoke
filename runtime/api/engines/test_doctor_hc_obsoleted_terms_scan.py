"""Tests for HC-obsoleted-terms scan behaviour and HC wiring.

Pattern + residue tests live in test_doctor_hc_obsoleted_terms.py.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.engines.obsoleted_terms_scan_test_support import (
    REPO_ROOT,
    StubDoctorArgs,
    db_router_items_command,
    retired_parent_epic_symbol,
)
from yoke_project_checks import check_obsoleted_terms
from yoke_project_checks.check_obsoleted_terms import (
    hc_obsoleted_terms,
    scan_repo,
)
from yoke_core.engines.doctor_report import RecordCollector

REPO = REPO_ROOT


# ---------------------------------------------------------------------------
# Scan behaviour on synthetic trees
# ---------------------------------------------------------------------------


def test_scan_detects_cli_form_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.md").write_text(
        f"Example: `{db_router_items_command('get', '5', 'epic')}`\n"
    )
    hits = scan_repo(tmp_path)
    assert any("epic" in hit for hit in hits), hits


def test_scan_detects_obsoleted_term_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "foo.md").write_text(
        f"This doc still references {retired_parent_epic_symbol()} in prose.\n"
    )
    hits = scan_repo(tmp_path)
    assert any(retired_parent_epic_symbol() in hit for hit in hits), hits


def test_scan_detects_sql_form_in_doc(tmp_path: Path):
    """Positive coverage: ``items WHERE epic={epic-id}`` and the screenshot-shape
    ``items WHERE epic_id IN (...)`` must both be detected by the scan."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_sql.md").write_text(
        "Look up the epic via:\n"
        "```sql\n"
        "SELECT id, status FROM items WHERE " + "epic" + "={epic-id};\n"
        "SELECT id FROM items WHERE " + "epic_id" + " IN (1511);\n"
        "```\n"
    )
    hits = scan_repo(tmp_path)
    assert len(hits) >= 2, hits
    assert any("epic" in h and "SQL form" in h for h in hits), hits


def test_scan_detects_sql_select_list_form_in_doc(tmp_path: Path):
    """Positive coverage: ``SELECT epic_id FROM items`` treats the retired field
    as an ``items`` column and must be detected by the scan."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_select.md").write_text(
        "```sql\n"
        "SELECT id, type, "
        + "epic_id"
        + " FROM items WHERE id IN (1515, 1516, 1517);\n"
        "```\n"
    )
    hits = scan_repo(tmp_path)
    assert any("SQL select-list form" in h for h in hits), hits


def test_scan_detects_epic_field_prose_in_doc(tmp_path: Path):
    """Positive coverage: ``the `epic` field on a backlog item`` prose must be
    detected by the scan."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_prose.md").write_text(
        "- `{epic-id}` — Epic name (matches the `"
        + "epic"
        + "` field on a backlog item)\n"
    )
    hits = scan_repo(tmp_path)
    assert any("prose form" in h for h in hits), hits


def test_scan_detects_child_issue_prose_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_ontology.md").write_text(
        "Never pre-file " + "child issues" + " for an unplanned epic.\n"
    )
    hits = scan_repo(tmp_path)
    assert any("child issue" in h for h in hits), hits


def test_scan_detects_type_issue_epic_parent_prose(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_guard.md").write_text(
        "Pre-decomposition guard: never file child issues (`"
        + "type=issue"
        + "` with an `epic` parent) for an unplanned epic.\n"
    )
    hits = scan_repo(tmp_path)
    # Both child-issue and type=issue+epic-parent patterns will fire here.
    assert any("type=issue with epic parent" in h for h in hits), hits


def test_scan_does_not_fire_on_legitimate_epic_tasks_sql(tmp_path: Path):
    """Negative coverage: ``epic_tasks WHERE epic_id IN (...)`` is the legitimate
    foreign-key reference and must NOT trigger the SQL pattern."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "valid.md").write_text(
        "```sql\n"
        "SELECT task_num FROM epic_tasks WHERE " + "epic_id" + " IN (1511, 1512);\n"
        "SELECT * FROM epic_tasks WHERE " + "epic_id" + "=? AND task_num=?;\n"
        "```\n"
    )
    assert scan_repo(tmp_path) == []


def test_scan_does_not_fire_on_qualified_epic_id_in_items_query(tmp_path: Path):
    """Negative coverage: ``items`` queries that filter on ``id={epic-id-...}``
    placeholders or on the literal ``type='epic'`` value must NOT trigger
    the SQL pattern, because the ``epic`` token is preceded by ``{``, ``-``,
    or ``'`` rather than a SQL delimiter from ``[\\s,(]``."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "valid_items.md").write_text(
        "```sql\n"
        "SELECT * FROM items i WHERE i.id={epic-id-number} AND i.type='"
        + "epic"
        + "';\n"
        "SELECT id FROM items WHERE id={epic-id} AND status='done';\n"
        "```\n"
    )
    assert scan_repo(tmp_path) == []


def test_scan_does_not_cross_python_query_arguments(tmp_path: Path):
    """A legitimate items.id query must not borrow ``epic_id`` from params."""
    target = tmp_path / "runtime" / "api"
    target.mkdir(parents=True)
    (target / "valid_items_query.py").write_text(
        'row = conn.execute("SELECT 1 FROM items WHERE id=%s", '
        "(int(epic_id),)).fetchone()\n",
        encoding="utf-8",
    )

    assert scan_repo(tmp_path) == []


def test_scan_does_not_fire_on_corrected_ontology_prose(tmp_path: Path):
    """Negative coverage: the corrected ontology that names the epic relation as
    ``the numeric `id` on the epic backlog item, which equals the `epic_id`
    foreign key in `epic_tasks``` must NOT trigger any pattern."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ontology.md").write_text(
        "## Backlog ontology\n"
        "\n"
        "Backlog items are flat rows in `items`. An epic is just an item with `type='"
        + "epic"
        + "'`. Epic decomposition lives in `epic_tasks`, keyed by "
        "`(epic_id, task_num)`, where `epic_id` IS the epic item's own numeric "
        "`items.id`. GitHub task issues are sync metadata for `epic_tasks`, not a "
        "child relationship in `items`.\n"
    )
    # The ontology paragraph names `items.id`, `epic_id`, and `epic_tasks` correctly
    # without using any retired surface name. No pattern should fire.
    assert scan_repo(tmp_path) == []


def test_scan_ignores_only_generated_strategy_renders(tmp_path: Path):
    (tmp_path / ".yoke" / "strategy").mkdir(parents=True)
    (tmp_path / ".yoke" / "strategy" / "WISPS.md").write_text(
        "WISP-15 considers parent linking and "
        + "child issues"
        + " for future generation.\n"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "untracked.md").write_text(
        "Live prose referencing " + "child issues" + " explicitly.\n"
    )
    hits = scan_repo(tmp_path)
    paths = {h.split(":", 1)[0] for h in hits}
    assert ".yoke/strategy/WISPS.md" not in paths, hits
    assert "docs/untracked.md" in paths, hits


def test_scan_ignores_archive_path(tmp_path: Path):
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "old.md").write_text(
        f"historical doc mentioning {retired_parent_epic_symbol()}\n"
    )
    assert scan_repo(tmp_path) == []


def test_scan_ignores_hc_self(tmp_path: Path):
    """The scanner declares its patterns as escaped regex, and exempts itself by
    module identity rather than by location, so a fresh scan finds nothing even
    when a copy of the scanner sits in a scanned tree.

    The source is read from the live module's own ``__file__`` so the fixture
    tracks the scanner wherever it lives.
    """
    source = Path(check_obsoleted_terms.__file__).read_text(encoding="utf-8")
    for rel_dir in (Path("runtime") / "api" / "engines", Path(".yoke") / "doctor"):
        hc_dir = tmp_path / rel_dir
        hc_dir.mkdir(parents=True)
        (hc_dir / Path(check_obsoleted_terms.__file__).name).write_text(source)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clean.md").write_text("nothing obsolete here\n")
    assert scan_repo(tmp_path) == []


# ---------------------------------------------------------------------------
# HC wiring — integration with RecordCollector
# ---------------------------------------------------------------------------


def test_hc_records_pass_on_clean_repo(monkeypatch, tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clean.md").write_text("nothing obsolete here\n")
    monkeypatch.setattr(
        "yoke_project_checks.check_obsoleted_terms._resolve_repo_root",
        lambda: str(tmp_path),
    )
    rec = RecordCollector()
    hc_obsoleted_terms(None, StubDoctorArgs(), rec)
    assert rec.fail_count == 0
    assert rec.warn_count == 0
    assert rec.pass_count == 1


def test_hc_records_warn_on_residue(monkeypatch, tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.md").write_text(
        f"Tutorial mentioning {retired_parent_epic_symbol()} and yoke-db.sh together.\n"
    )
    monkeypatch.setattr(
        "yoke_project_checks.check_obsoleted_terms._resolve_repo_root",
        lambda: str(tmp_path),
    )
    rec = RecordCollector()
    hc_obsoleted_terms(None, StubDoctorArgs(), rec)
    assert rec.fail_count == 0
    assert rec.warn_count == 1
    assert rec.pass_count == 0


def test_scan_widening_catches_slash_form_module_path(tmp_path: Path):
    """Un-patched ``Path("runtime/harness/codex/codex_hooks_tool_events.py")``
    in a runtime Python source flips the scanner via slash-form normalisation."""
    target = tmp_path / "runtime" / "api" / "engines"
    target.mkdir(parents=True)
    (target / "stale_module.py").write_text(
        "from pathlib import Path\n"
        '_BAD = Path("runtime/harness/codex/codex_hooks_tool_events.py")\n',
        encoding="utf-8",
    )
    hits = scan_repo(tmp_path)
    assert any(
        "codex_hooks_tool_events" in h and "runtime/api/engines/stale_module.py" in h
        for h in hits
    ), hits


def test_scan_widening_catches_dotted_form_hook_module(tmp_path: Path):
    """Dotted-form retired hook module reference in a runtime Python
    source flips the scanner via the standard dotted pattern."""
    target = tmp_path / "runtime" / "api" / "engines"
    target.mkdir(parents=True)
    (target / "stale_hook.py").write_text(
        '"runtime.harness.session_hooks user-prompt-submit-hook"\n',
        encoding="utf-8",
    )
    hits = scan_repo(tmp_path)
    assert any(
        "session_hooks" in h and "runtime/api/engines/stale_hook.py" in h for h in hits
    ), hits


def test_scan_widening_python_path_allowlist_is_path_scoped(tmp_path: Path):
    """An allow-listed prefix exempts files under it from the
    ``yoke-db.sh`` pattern; a sibling outside the allow-list still trips.
    The exemption is path-scoped (file-level), not pattern-wide (global)."""
    allow_dir = tmp_path / "runtime" / "api" / "domain"
    allow_dir.mkdir(parents=True)
    (allow_dir / "lint_db_rules_fixture.py").write_text(
        '_RETIRED = "yoke-db.sh"\n',
        encoding="utf-8",
    )
    (allow_dir / "new_module.py").write_text(
        '_LEAK = "yoke-db.sh runs find-by-item"\n',
        encoding="utf-8",
    )
    paths = {hit.split(":", 1)[0] for hit in scan_repo(tmp_path)}
    assert "runtime/api/domain/lint_db_rules_fixture.py" not in paths
    assert "runtime/api/domain/new_module.py" in paths


def test_scan_widening_skips_python_files_outside_runtime(tmp_path: Path):
    """``.py`` scanning is scoped to ``runtime/`` only — Python files
    under ``docs/`` are not in scope."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.py").write_text(
        '_BAD = "yoke-db.sh"\n',
        encoding="utf-8",
    )
    assert scan_repo(tmp_path) == []
