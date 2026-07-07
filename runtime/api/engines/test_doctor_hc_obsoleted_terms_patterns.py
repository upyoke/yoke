"""Tests for the current HC-obsoleted-terms epic-link ontology patterns in
``doctor_hc_obsoleted_terms.py``: SQL form, prose form, child-issue prose,
and the ``type=issue with an epic parent`` ontology phrase. Covers both the
pattern-shape behaviour (compile + match positives and negatives) and the
git-grep residue checks for the matching AC-5 verification surfaces.

Pre-existing pattern shape and residue tests live in
``test_doctor_hc_obsoleted_terms.py``. Scan-on-synthetic-tree and HC-wiring
tests live in ``test_doctor_hc_obsoleted_terms_scan.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_hc_obsoleted_terms import (
    _PER_PATTERN_PATH_ALLOWLIST,
    _RETIRED_CHILD_ISSUE_PATTERN,
    _RETIRED_EPIC_FIELD_PROSE_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_PATTERN,
    _RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN,
)
from runtime.api.engines.test_doctor_hc_obsoleted_terms import (
    _AUTHORIZED_DECLARATION_PATHS,
    _filter_tolerated,
    _run_git_grep,
)


def test_sql_form_pattern_matches_screenshot_shape_and_other_stale_uses():
    """The retired-parent-epic SQL pattern must catch every WHERE-clause stale
    shape that treats ``epic`` or ``epic_id`` as a column on ``items``: the
    screenshot regression ``items WHERE epic_id IN (...)`` and the
    merge/plan/simulate SQL forms ``items WHERE epic={epic-id}``.

    Note: the SELECT-list shape ``SELECT epic_id FROM items WHERE id IN (...)``
    is not targeted by this pattern because catching unqualified column names
    in SELECT lists without false-positives on legitimate ``epic_tasks``
    queries is not feasible with a single-line regex. The WHERE-clause shape
    is the dominant stale form across merge/plan/simulate prompt residue."""
    compiled = re.compile(_RETIRED_PARENT_EPIC_SQL_PATTERN)
    for line in [
        # Screenshot regression shape from the operator evidence (WHERE form).
        "SELECT id, type, title FROM items WHERE " + "epic_id" + " IN (1511) AND id != 1511",
        # Stale merge/plan/simulate forms with `epic=`.
        "SELECT id, status FROM items WHERE " + "epic" + "={epic-id};",
        "SELECT COUNT(*) FROM items WHERE " + "epic" + "={epic-id} LIMIT 1",
        "SELECT id FROM items WHERE " + "epic" + "='{epic-id}'",
        # Plan/SKILL.md compound predicate that mixed `id=` with the retired
        # `epic=` predicate on the same `items` query.
        "SELECT id FROM items WHERE id={N} OR " + "epic" + "={epic-id} ORDER BY id",
    ]:
        assert compiled.search(line), f"expected SQL-form match on: {line!r}"


def test_sql_select_list_pattern_matches_screenshot_shape():
    """The retired-parent-epic select-list pattern must catch stale queries that
    select ``epic`` or ``epic_id`` as if it were a column on ``items``."""
    compiled = re.compile(_RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN)
    for line in [
        "SELECT id, type, " + "epic_id" + " FROM items WHERE id IN (1515, 1516, 1517);",
        "SELECT id, " + "epic" + " FROM items WHERE id={N};",
    ]:
        assert compiled.search(line), f"expected SQL select-list match on: {line!r}"


def test_sql_select_list_pattern_does_not_match_correct_items_queries():
    """The select-list pattern must NOT fire on valid items queries that mention
    ``epic`` only in type filters or ID placeholders after the FROM clause."""
    compiled = re.compile(_RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN)
    for line in [
        "SELECT id, title, type, status FROM items WHERE id={epic-id} AND type='epic';",
        "SELECT COALESCE(github_issue, '') FROM items WHERE id={epic-id-number};",
        "SELECT task_num, " + "epic_id" + " FROM epic_tasks WHERE " + "epic_id" + " IN (1511);",
    ]:
        assert not compiled.search(line), f"unexpected SQL select-list match on: {line!r}"


def test_sql_form_pattern_does_not_match_legitimate_epic_tasks_sql():
    """The SQL pattern must NOT fire on legitimate ``epic_tasks WHERE epic_id``
    SQL (no ``items`` token at all), or on placeholder names like
    ``{epic-id}`` / ``{epic-id-number}`` where ``epic`` is preceded by a
    non-SQL-delimiter character.

    Known limitation: lines that join ``items`` and ``epic_tasks`` via a
    nested ``(SELECT epic_id FROM epic_tasks ...)`` subquery on the same line
    can false-positive — the regex sees ``items WHERE ... <space>epic_id``
    and cannot tell that the unqualified ``epic_id`` belongs to the inner
    ``epic_tasks`` query. The accepted remediation when this happens is to
    split the SQL across multiple lines so the inner subquery is on its own
    line. In practice, scanned ``.md`` SQL snippets keep one statement per
    line, so this case does not arise on the live tree."""
    compiled = re.compile(_RETIRED_PARENT_EPIC_SQL_PATTERN)
    for line in [
        # Legitimate epic_tasks.epic_id SQL — no items token, must not match.
        "SELECT * FROM epic_tasks WHERE " + "epic_id" + " IN (1511, 1512)",
        "SELECT task_num FROM epic_tasks WHERE " + "epic_id" + " = ?",
        # Placeholder uses where ``epic`` is part of a longer hyphenated token.
        "SELECT COALESCE(github_issue, '') FROM items WHERE id={epic-id-number};",
        "SELECT id FROM items WHERE id={epic-id} AND " + "type" + "='epic' LIMIT 1",
        # ``epic`` as a quoted SQL string literal in items queries (filter on type).
        "SELECT id FROM items i WHERE i.type='" + "epic" + "' AND status='done'",
    ]:
        assert not compiled.search(line), f"unexpected SQL-form match on: {line!r}"


def test_prose_field_on_item_pattern_matches_backtick_and_bare_forms():
    """The retired epic-field prose pattern must catch the merge/simulate
    SKILL.md prose ``the `epic` field on a backlog item`` and the bare
    variant without backticks."""
    compiled = re.compile(_RETIRED_EPIC_FIELD_PROSE_PATTERN)
    for line in [
        "matches the `" + "epic" + "` field on the backlog item in the DB",
        "matches the `" + "epic" + "` field on a backlog item, or the `epic_id`",
        # Bare form without backticks.
        "the " + "epic" + " field on the item is set to the parent ID",
    ]:
        assert compiled.search(line), f"expected prose-form match on: {line!r}"


def test_prose_field_on_item_pattern_does_not_match_correct_ontology():
    """The prose pattern must NOT fire on the corrected ontology that names
    the relation as ``id on the epic backlog item``."""
    compiled = re.compile(_RETIRED_EPIC_FIELD_PROSE_PATTERN)
    for line in [
        "the numeric `id` on the epic backlog item, which equals the `epic_id` foreign key",
        "the numeric `id` on the epic item",
        "the `epic_id` foreign key in `epic_tasks`",
    ]:
        assert not compiled.search(line), f"unexpected prose match on: {line!r}"


def test_child_issue_pattern_matches_backlog_ontology_prose():
    """The child-issue pattern must catch ``child issue`` and ``child issues``
    as bare backlog-ontology phrases."""
    compiled = re.compile(_RETIRED_CHILD_ISSUE_PATTERN)
    for line in [
        "Do not pre-file " + "child issues" + " for an epic",
        "Never file " + "child issue" + " rows for unplanned epics",
    ]:
        assert compiled.search(line), f"expected child-issue match on: {line!r}"


def test_child_issue_pattern_does_not_match_unrelated_phrases():
    """The pattern must NOT fire on ``child items`` (different word) or on
    ``child of issue`` (no adjacent ``child issue``)."""
    compiled = re.compile(_RETIRED_CHILD_ISSUE_PATTERN)
    for line in [
        "Backlog items are flat rows; there are no child items in `items`.",
        "`child` of `issue` ordering is undefined for sibling rows",
    ]:
        assert not compiled.search(line), f"unexpected child-issue match on: {line!r}"


def test_type_issue_epic_parent_pattern_matches_backtick_wrapped_form():
    """The pattern must catch the stale ``\\`type=issue\\` with an \\`epic\\` parent``
    shape from infer-and-create.md, including the backtick wrapping that a
    naive ``\\bepic\\s+parent\\b`` regex would miss."""
    compiled = re.compile(_RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN)
    for line in [
        "Never file child issues (`" + "type=issue" + "` with an `epic` parent) for an epic",
        # Bare un-backticked form.
        "items where " + "type=issue" + " and the epic parent is set",
    ]:
        assert compiled.search(line), f"expected type=issue+epic-parent match on: {line!r}"


def test_type_issue_epic_parent_pattern_does_not_match_unrelated_uses():
    """The pattern must NOT fire on lines that mention ``type=issue`` and
    ``epic`` and ``parent`` in unrelated clauses far apart, or on the
    GitHub-side ``epic parent issue`` sync metadata phrasing where ``type=issue``
    is absent."""
    compiled = re.compile(_RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN)
    for line in [
        # type=issue without any epic/parent on the same line.
        "Conduct rejects items with " + "type=issue" + " and exits early.",
        # epic parent without type=issue (GitHub sync metadata).
        "Look up the epic's parent GitHub issue number from the DB",
        # type=issue and epic mentioned far apart, no parent token.
        "When " + "type=issue" + " advances to refined-idea, the epic taxonomy stays untouched.",
    ]:
        assert not compiled.search(line), f"unexpected type=issue+epic-parent match on: {line!r}"


def test_strategy_files_are_in_per_pattern_allowlist():
    """The child-issue pattern keeps narrow strategy-file waivers."""
    allow = _PER_PATTERN_PATH_ALLOWLIST.get(_RETIRED_CHILD_ISSUE_PATTERN, ())
    assert ".yoke/strategy/WISPS.md" in allow


# ---------------------------------------------------------------------------
# Residue checks — AC-5 verification greps
# ---------------------------------------------------------------------------


def test_items_where_epic_sql_form_has_no_live_residue():
    """AC-5 (SQL form): ``items WHERE epic=…`` and the screenshot-shape
    ``items WHERE epic_id IN (…)`` must not appear in any tracked file
    outside the authorized declaration paths and the strategy/archive
    waivers documented in AC-8."""
    hits = _run_git_grep(r"items[^\n]*WHERE[^\n]*[ ,(]epic(_id)?[ )=;]")
    tolerated_paths = _AUTHORIZED_DECLARATION_PATHS + (
        ".yoke/strategy/WISPS.md",
    )
    tolerated = _filter_tolerated(hits, allow_path_substrings=tolerated_paths)
    assert not tolerated, (
        "stale `items WHERE epic[_id]` SQL must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_items_select_epic_sql_form_has_no_live_residue():
    """Select-list form: ``SELECT epic[_id] FROM items`` must not appear in
    tracked files outside the authorized declaration paths."""
    hits = _run_git_grep(r"SELECT[^\n]*[ ,(]epic(_id)?[ ,)][^\n]*FROM +items")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "stale `SELECT epic[_id] FROM items` SQL must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_epic_field_on_item_prose_has_no_live_residue():
    """AC-5 (prose form): ``epic field on a backlog item`` (bare or
    backtick-wrapped) must not appear in any tracked file outside the
    authorized declaration paths."""
    hits = _run_git_grep(r"[`'\"]?epic[`'\"]?[ ]*field[ ]+on[ ]+(a|the)[ ]+(backlog[ ]+)?item")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "stale `epic field on a backlog item` prose must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_child_issue_phrase_has_no_live_residue():
    """AC-5 (child-issue prose): ``child issue`` / ``child issues`` must not
    appear in any tracked file outside the strategy/archive waivers."""
    hits = _run_git_grep(r"child[ ]+issues?")
    tolerated_paths = _AUTHORIZED_DECLARATION_PATHS + (
        ".yoke/strategy/WISPS.md",
    )
    tolerated = _filter_tolerated(hits, allow_path_substrings=tolerated_paths)
    assert not tolerated, (
        "stale `child issue(s)` backlog ontology phrase must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_type_issue_epic_parent_phrase_has_no_live_residue():
    """AC-5 (type=issue + epic parent prose): the retired ``type=issue with
    an epic parent`` shape from infer-and-create.md must not appear in any
    tracked file outside the authorized declaration paths."""
    hits = _run_git_grep(r"type=issue.+epic.+parent")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "stale `type=issue ... epic parent` prose must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )
