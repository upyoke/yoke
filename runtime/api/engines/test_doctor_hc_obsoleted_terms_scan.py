"""Tests for HC-obsoleted-terms scan behaviour and HC wiring.

Pattern + residue tests live in test_doctor_hc_obsoleted_terms.py.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_hc_obsoleted_terms import (
    hc_obsoleted_terms,
    scan_repo,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Cannot locate repo root")


REPO = _repo_root()


def _retired_parent_epic_symbol() -> str:
    return "items" + "." + "epic"


def _db_router_items_cmd(verb: str, item_ref: str, field: str, value: str = "") -> str:
    parts = [
        "python3 -m yoke_core.cli.db_router",
        "items",
        verb,
        item_ref,
        field,
    ]
    if value:
        parts.append(value)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Scan behaviour on synthetic trees
# ---------------------------------------------------------------------------


def test_scan_detects_cli_form_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.md").write_text(
        f"Example: `{_db_router_items_cmd('get', '5', 'epic')}`\n"
    )
    hits = scan_repo(tmp_path)
    assert any("epic" in hit for hit in hits), hits


def test_scan_detects_obsoleted_term_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "foo.md").write_text(
        f"This doc still references {_retired_parent_epic_symbol()} in prose.\n"
    )
    hits = scan_repo(tmp_path)
    assert any(_retired_parent_epic_symbol() in hit for hit in hits), hits


def test_scan_detects_sql_form_in_doc(tmp_path: Path):
    """AC-4 positive: ``items WHERE epic={epic-id}`` and the screenshot-shape
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
        "SELECT id, type, " + "epic_id" + " FROM items WHERE id IN (1515, 1516, 1517);\n"
        "```\n"
    )
    hits = scan_repo(tmp_path)
    assert any("SQL select-list form" in h for h in hits), hits


def test_scan_detects_epic_field_prose_in_doc(tmp_path: Path):
    """AC-4 positive: ``the `epic` field on a backlog item`` prose must be
    detected by the scan."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_prose.md").write_text(
        "- `{epic-id}` — Epic name (matches the `" + "epic" + "` field on a backlog item)\n"
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
        + "type=issue" + "` with an `epic` parent) for an unplanned epic.\n"
    )
    hits = scan_repo(tmp_path)
    # Both child-issue and type=issue+epic-parent patterns will fire here.
    assert any("type=issue with epic parent" in h for h in hits), hits


def test_scan_does_not_fire_on_legitimate_epic_tasks_sql(tmp_path: Path):
    """AC-7 negative: ``epic_tasks WHERE epic_id IN (...)`` is the legitimate
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
    """AC-7 negative: ``items`` queries that filter on ``id={epic-id-...}``
    placeholders or on the literal ``type='epic'`` value must NOT trigger
    the SQL pattern, because the ``epic`` token is preceded by ``{``, ``-``,
    or ``'`` rather than a SQL delimiter from ``[\\s,(]``."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "valid_items.md").write_text(
        "```sql\n"
        "SELECT * FROM items i WHERE i.id={epic-id-number} AND i.type='" + "epic" + "';\n"
        "SELECT id FROM items WHERE id={epic-id} AND status='done';\n"
        "```\n"
    )
    assert scan_repo(tmp_path) == []


def test_scan_does_not_fire_on_corrected_ontology_prose(tmp_path: Path):
    """AC-7 negative: the corrected ontology that names the epic relation as
    ``the numeric `id` on the epic backlog item, which equals the `epic_id`
    foreign key in `epic_tasks``` must NOT trigger any pattern."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ontology.md").write_text(
        "## Backlog ontology\n"
        "\n"
        "Backlog items are flat rows in `items`. An epic is just an item with `type='"
        + "epic" + "'`. Epic decomposition lives in `epic_tasks`, keyed by "
        "`(epic_id, task_num)`, where `epic_id` IS the epic item's own numeric "
        "`items.id`. GitHub task issues are sync metadata for `epic_tasks`, not a "
        "child relationship in `items`.\n"
    )
    # The ontology paragraph names `items.id`, `epic_id`, and `epic_tasks` correctly
    # without using any retired surface name. No pattern should fire.
    assert scan_repo(tmp_path) == []


def test_scan_per_pattern_allowlist_exempts_strategy_files(tmp_path: Path):
    """The child-issue pattern allows only named strategy-file waivers."""
    (tmp_path / ".yoke" / "strategy").mkdir(parents=True)
    (tmp_path / ".yoke" / "strategy" / "WISPS.md").write_text(
        "WISP-15 considers parent linking and " + "child issues" + " for future generation.\n"
    )
    # A non-exempt strategy file must still trigger the pattern, proving the
    # exemption is path-scoped rather than blanket-suppressing the pattern.
    (tmp_path / ".yoke" / "strategy" / "OTHER.md").write_text(
        "Future plans referencing " + "child issues" + " explicitly.\n"
    )
    hits = scan_repo(tmp_path)
    paths = {h.split(":", 1)[0] for h in hits}
    assert ".yoke/strategy/WISPS.md" not in paths, hits
    assert ".yoke/strategy/OTHER.md" in paths, hits


def test_scan_ignores_archive_path(tmp_path: Path):
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "old.md").write_text(
        f"historical doc mentioning {_retired_parent_epic_symbol()}\n"
    )
    assert scan_repo(tmp_path) == []


def test_scan_ignores_hc_self(tmp_path: Path):
    """The HC file declares patterns as escaped regex. The escaped form does not
    contain the bare term as a substring, so a fresh scan should find nothing
    even when the HC file is part of the scanned tree."""
    hc_dir = tmp_path / "runtime" / "api" / "engines"
    hc_dir.mkdir(parents=True)
    copy_of_hc = hc_dir / "doctor_hc_obsoleted_terms.py"
    source = Path(
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "engines"
        / "doctor_hc_obsoleted_terms.py"
    ).read_text(encoding="utf-8")
    copy_of_hc.write_text(source)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clean.md").write_text("nothing obsolete here\n")
    assert scan_repo(tmp_path) == []


# ---------------------------------------------------------------------------
# HC wiring — integration with RecordCollector
# ---------------------------------------------------------------------------


class _StubArgs(DoctorArgs):
    def __init__(self) -> None:
        self.only = None
        self.quick = False
        self.project = None
        self.json_output = False
        self.file = None


def test_hc_records_pass_on_clean_repo(monkeypatch, tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clean.md").write_text("nothing obsolete here\n")
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_obsoleted_terms._resolve_repo_root",
        lambda: str(tmp_path),
    )
    rec = RecordCollector()
    hc_obsoleted_terms(None, _StubArgs(), rec)
    assert rec.fail_count == 0
    assert rec.warn_count == 0
    assert rec.pass_count == 1


def test_hc_records_warn_on_residue(monkeypatch, tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.md").write_text(
        f"Tutorial mentioning {_retired_parent_epic_symbol()} and yoke-db.sh together.\n"
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_obsoleted_terms._resolve_repo_root",
        lambda: str(tmp_path),
    )
    rec = RecordCollector()
    hc_obsoleted_terms(None, _StubArgs(), rec)
    assert rec.fail_count == 0
    assert rec.warn_count == 1
    assert rec.pass_count == 0

def test_scan_widening_catches_slash_form_module_path(tmp_path: Path):
    """AC-2: un-patched ``Path("runtime/harness/codex/codex_hooks_tool_events.py")``
    in a runtime Python source flips the scanner via slash-form normalisation."""
    target = tmp_path / "runtime" / "api" / "engines"
    target.mkdir(parents=True)
    (target / "stale_module.py").write_text(
        'from pathlib import Path\n'
        '_BAD = Path("runtime/harness/codex/codex_hooks_tool_events.py")\n',
        encoding="utf-8",
    )
    hits = scan_repo(tmp_path)
    assert any(
        "codex_hooks_tool_events" in h
        and "runtime/api/engines/stale_module.py" in h
        for h in hits
    ), hits


def test_scan_widening_catches_dotted_form_hook_module(tmp_path: Path):
    """AC-3: dotted-form retired hook module reference in a runtime Python
    source flips the scanner via the standard dotted pattern."""
    target = tmp_path / "runtime" / "api" / "engines"
    target.mkdir(parents=True)
    (target / "stale_hook.py").write_text(
        '"runtime.harness.session_hooks user-prompt-submit-hook"\n',
        encoding="utf-8",
    )
    hits = scan_repo(tmp_path)
    assert any(
        "session_hooks" in h
        and "runtime/api/engines/stale_hook.py" in h
        for h in hits
    ), hits


def test_scan_widening_python_path_allowlist_is_path_scoped(tmp_path: Path):
    """AC-7: an allow-listed prefix exempts files under it from the
    ``yoke-db.sh`` pattern; a sibling outside the allow-list still trips.
    The exemption is path-scoped (file-level), not pattern-wide (global)."""
    allow_dir = tmp_path / "runtime" / "api" / "tools"
    allow_dir.mkdir(parents=True)
    (allow_dir / "shell_inventory_test_fixture.py").write_text(
        '_RETIRED = "yoke-db.sh"\n', encoding="utf-8",
    )
    leak_dir = tmp_path / "runtime" / "api" / "domain"
    leak_dir.mkdir(parents=True)
    (leak_dir / "new_module.py").write_text(
        '_LEAK = "yoke-db.sh runs find-by-item"\n', encoding="utf-8",
    )
    paths = {hit.split(":", 1)[0] for hit in scan_repo(tmp_path)}
    assert "runtime/api/tools/shell_inventory_test_fixture.py" not in paths
    assert "runtime/api/domain/new_module.py" in paths


def test_scan_widening_skips_python_files_outside_runtime(tmp_path: Path):
    """AC-1: ``.py`` scanning is scoped to ``runtime/`` only — Python files
    under ``docs/`` or ``.yoke/strategy/`` are not in scope (the .md scan covers
    those dirs)."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale.py").write_text(
        '_BAD = "yoke-db.sh"\n', encoding="utf-8",
    )
    assert scan_repo(tmp_path) == []


def test_scan_repo_clean_on_real_main():
    """AC-4/AC-8: the live repo has no retired-term residue in any scanned
    surface. The widened scanner (``.py`` under ``runtime/`` plus slash-form
    normalisation) reports zero hits on main."""
    hits = scan_repo(REPO)
    assert hits == [], (
        "Live repo has retired-term residue. Fix the offending file or add "
        "a justified allow-list entry to doctor_hc_obsoleted_terms_allowlists.\n"
        + "\n".join(hits[:20])
    )
