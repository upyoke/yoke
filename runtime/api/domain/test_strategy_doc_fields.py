"""Strategy fields remain valid across authoring, ingest, and history writes."""

from pathlib import Path

import pytest

from yoke_contracts.project_contract.strategy_doc_fields import (
    FIELD_LIMITS,
    StrategyDocFieldError,
    field_heading,
    insert_fields,
    normalize_fields,
    read_field,
    validate_field,
)
from yoke_core.domain.strategy_doc_presentation import (
    state_from_content,
    summary_from_content,
)
from yoke_core.domain.strategy_doc_sections import replace_section
from yoke_core.domain.strategy_docs_defaults import (
    DEFAULT_STRATEGY_DOC_SLUGS,
    placeholder_content,
)


def document(summary="A strategy document.", state="In progress"):
    return normalize_fields(
        insert_fields(
            "# Plan\n\n## Body\n\nKeep this body.\n", Summary=summary, State=state
        )[0]
    )


@pytest.mark.parametrize("name", FIELD_LIMITS)
def test_character_limit_counts_unicode_and_trims(name):
    limit = FIELD_LIMITS[name]
    assert validate_field(name, "  " + "é" * limit + "  ") == "é" * limit
    with pytest.raises(StrategyDocFieldError) as error:
        validate_field(name, "é" * (limit + 1))
    assert str(limit + 1) in str(error.value)
    assert field_heading(name) in str(error.value)


@pytest.mark.parametrize("value", ["", "   ", "first\nsecond", "first\n", "first\r"])
def test_create_field_rejects_empty_and_newlines(value):
    with pytest.raises(StrategyDocFieldError, match="one non-empty line"):
        insert_fields("# Plan", Summary=value, State="draft")


def test_create_replaces_duplicate_body_copies_and_inserts_after_title():
    body = "# Plan\n\n## SUMMARY\n\nOld.\n\n## Summary (999 chars max)\n\nOther.\n\n## State\n\nOld state.\n\n## Body\n\nUnchanged.\n"
    content, replaced = insert_fields(
        body, Summary="New summary.", State="Needs review"
    )
    content = normalize_fields(content)
    assert replaced == ["State", "Summary"]
    assert content.startswith(f"# Plan\n\n{field_heading('Summary')}\n\nNew summary.")
    assert content.count(field_heading("Summary")) == 1
    assert state_from_content(content) == "Needs review"
    assert content.endswith("## Body\n\nUnchanged.\n")


def test_create_without_h1_puts_fields_at_top():
    content, _ = insert_fields("## Body\n\nUnchanged.", Summary="Short.", State="draft")
    assert normalize_fields(content).startswith(field_heading("Summary"))


def test_legacy_and_suffix_edits_normalize_case_insensitively():
    content = "# Plan\n\n## sUMMARY (999 chars max)\n\n  Purpose.  \n\n## STATE\n\nBlocked on QA\n\n## Body\n\nDetails.\n"
    normalized = normalize_fields(content)
    assert field_heading("Summary") in normalized
    assert field_heading("State") in normalized
    assert "999" not in normalized
    assert normalize_fields(normalized) == normalized
    assert summary_from_content(normalized) == "Purpose."
    assert state_from_content(normalized) == "Blocked on QA"


@pytest.mark.parametrize("name", FIELD_LIMITS)
@pytest.mark.parametrize(
    "kind", ["missing", "duplicated", "empty", "multiline", "long"]
)
def test_edit_refuses_invalid_field_with_fix(name, kind):
    heading = field_heading(name)
    content = document()
    if kind == "missing":
        content = content.replace(heading, "## Other")
    elif kind == "duplicated":
        content += f"\n{heading}\n\nExtra.\n"
    else:
        value = {
            "empty": "",
            "multiline": "First.\nSecond.",
            "long": "x" * (FIELD_LIMITS[name] + 1),
        }[kind]
        content = replace_section(content, name, value)
    with pytest.raises(StrategyDocFieldError) as error:
        normalize_fields(content)
    message = str(error.value)
    assert heading in message
    assert str(FIELD_LIMITS[name]) in message
    assert "characters" in message
    assert "one" in message


@pytest.mark.parametrize("suffix", ["", " (999 chars max)"])
def test_section_replace_accepts_field_heading_with_any_suffix(suffix):
    result = normalize_fields(
        replace_section(document(), "State" + suffix, "Awaiting input")
    )
    assert read_field(result, "State") == "Awaiting input"


def test_fenced_examples_are_not_duplicate_fields():
    content = (
        document()
        + "\n```markdown\n## Summary\n\nAn example.\n## State\n\nexample\n```\n"
    )
    assert read_field(normalize_fields(content), "Summary") == "A strategy document."


def test_defaults_remain_compliant_for_long_project_names():
    for slug in DEFAULT_STRATEGY_DOC_SLUGS:
        content = placeholder_content(slug, "Very long project name " * 20)
        assert normalize_fields(content) == content
        assert read_field(content, "State") == "draft"


@pytest.fixture
def connection(tmp_path: Path, monkeypatch):
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def test_writes_refuse_invalid_fields_without_changing_row(connection):
    from yoke_core.domain.strategy_docs import get_doc, replace_doc
    from yoke_core.domain.strategy_docs_create import create_doc
    from yoke_core.domain.strategy_docs_header import render_file_text
    from yoke_core.domain.strategy_docs_ingest import plan_ingest

    create_doc(
        connection,
        1,
        "FIELD-TEST",
        "# Plan\n\n## Body\n\nDetails.\n",
        None,
        summary="Purpose.",
        state="draft",
    )
    before = get_doc(connection, 1, "FIELD-TEST")
    invalid = replace_section(
        before["content"], "State", "x" * (FIELD_LIMITS["State"] + 1)
    )
    with pytest.raises(StrategyDocFieldError):
        replace_doc(
            connection,
            1,
            "FIELD-TEST",
            invalid,
            None,
            base_updated_at=before["updated_at"],
            force=True,
        )
    text = render_file_text(
        slug="FIELD-TEST", content=before["content"], updated_at=before["updated_at"]
    )
    # Keep the rendered CAS header while changing only its body.
    header = text.split("\n", 1)[0]
    with pytest.raises(StrategyDocFieldError):
        plan_ingest(
            connection,
            project_id=1,
            files=[{"slug": "FIELD-TEST", "text": header + "\n" + invalid}],
        )
    assert get_doc(connection, 1, "FIELD-TEST") == before


def test_restore_repairs_legacy_revision_only_with_explicit_fields(connection):
    from yoke_core.domain.strategy_docs import get_doc
    from yoke_core.domain.strategy_docs_create import create_doc
    from yoke_core.domain.strategy_docs_schema import record_doc_revision
    from yoke_core.domain.strategy_doc_history import restore_doc_revision

    create_doc(
        connection,
        1,
        "HISTORY-TEST",
        "# Plan\n\n## Body\n\nDetails.\n",
        None,
        summary="Purpose.",
        state="draft",
    )
    revision = record_doc_revision(
        connection,
        1,
        "HISTORY-TEST",
        "# Old plan\n\nLegacy body.\n",
        source_operation="replace",
        actor_id=None,
        created_at="2026-09-30T00:00:00Z",
    )
    connection.commit()
    before = get_doc(connection, 1, "HISTORY-TEST")
    with pytest.raises(StrategyDocFieldError, match="--summary / --state"):
        restore_doc_revision(
            connection,
            1,
            "HISTORY-TEST",
            revision,
            base_updated_at=before["updated_at"],
            actor_id=None,
        )
    restore_doc_revision(
        connection,
        1,
        "HISTORY-TEST",
        revision,
        base_updated_at=before["updated_at"],
        actor_id=None,
        summary="Legacy purpose.",
        state="reference",
    )
    restored = get_doc(connection, 1, "HISTORY-TEST")
    assert read_field(restored["content"], "Summary") == "Legacy purpose."
    assert "Legacy body." in restored["content"]
