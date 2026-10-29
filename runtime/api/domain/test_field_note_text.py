"""Lock the canonical text of ``field_note_text``."""

from __future__ import annotations

from yoke_contracts import field_note_text as fnt


def test_kind_values_canonical_enum() -> None:
    assert fnt.KIND_VALUES == ("failed", "new", "unclear", "observation")


def test_evidence_max_chars_is_shared_contract() -> None:
    assert fnt.EVIDENCE_MAX_CHARS == 4000


def test_directive_canonical_text() -> None:
    assert fnt.DIRECTIVE == (
        "File a field note each time a recipe, help text or refusal is wrong "
        "or missing, or you spot a bug outside your task — before moving on. "
        "If you already filed the same problem, add `--correlation-id "
        "<that note's id>`:"
    )


def test_basic_recipe_canonical_text() -> None:
    assert fnt.BASIC_RECIPE == (
        "yoke feedback --to yoke "
        "--category <failed|new|unclear|observation> --evidence '...'"
    )


def test_footer_is_directive_and_recipe() -> None:
    assert fnt.FOOTER == f"{fnt.DIRECTIVE}\n{fnt.BASIC_RECIPE}"
    assert "field-note append --help" not in fnt.FOOTER


def test_denial_footer_canonical_text() -> None:
    assert fnt.DENIAL_FOOTER == (
        "If this fix is wrong, file a field note: "
        "yoke feedback --to yoke --category failed --evidence '...'"
    )


def test_help_body_canonical_text() -> None:
    assert fnt.HELP_BODY == (
        "File a field note each time a recipe, help text or refusal is wrong "
        "or missing, or you spot a bug outside your task — before moving on. "
        "Link a repeat with `--correlation-id <first note's id>`.\n"
        "\n"
        "Kinds:\n"
        "- failed: a recipe, help text or refusal gave a wrong result\n"
        "- new: no recipe or help covered what you needed\n"
        "- unclear: two surfaces disagree, or the guidance is ambiguous\n"
        "- observation: a bug or oddity outside your current task\n"
        "\n"
        "Correlated evidence is stored under the root note and excluded from "
        "unreviewed counts. "
        "Do not file progress or a routine recovery that worked."
    )


def test_correlation_id_help_canonical_text() -> None:
    assert fnt.CORRELATION_ID_HELP == (
        "Integer id of the first field note for this problem in this project. "
        "Find it with yoke feedback list. Run labels are not root ids."
    )


def test_module_exports_are_plain_data() -> None:
    import inspect

    for name in fnt.__all__:
        value = getattr(fnt, name)
        assert not inspect.isfunction(value), name
        assert not inspect.ismethod(value), name
