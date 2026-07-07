"""Lock the canonical text shape of ``field_note_text``.

Tests assert full constant strings (not partial matches) so any drift in the
directive language, the basic recipe form, or the help pointer hits the test
before lint. The worked-mode catalog is locked by count, kind enum membership,
and field non-emptiness so adding or dropping a mode requires touching this
test.
"""

from __future__ import annotations

from yoke_contracts import field_note_text as fnt


_VALID_KINDS = frozenset({"failed", "new", "unclear", "observation"})


def test_kind_values_canonical_enum() -> None:
    assert fnt.KIND_VALUES == ("failed", "new", "unclear", "observation")
    assert set(fnt.KIND_VALUES) == _VALID_KINDS


def test_kind_observation_definition_is_canonical_text() -> None:
    assert fnt.KIND_OBSERVATION_DEFINITION == (
        "minor bug, surprise, or stale reference noticed during unrelated work. "
        "Not in current scope. Not worth a ticket today."
    )


def test_directive_canonical_text() -> None:
    assert fnt.DIRECTIVE == (
        "When you hit a recipe gap or notice a minor bug not worth a ticket, "
        "file a field-note immediately — before retrying, before moving on."
    )


def test_basic_recipe_canonical_text() -> None:
    assert fnt.BASIC_RECIPE == (
        "yoke ouroboros field-note append "
        "--kind <failed|new|unclear|observation> --evidence '...'"
    )


def test_help_pointer_canonical_text() -> None:
    assert fnt.HELP_POINTER == (
        "Run `yoke ouroboros field-note append --help` "
        "for the worked failure modes and decision tree."
    )


def test_footer_is_three_line_assembly() -> None:
    assert fnt.FOOTER == f"{fnt.DIRECTIVE}\n{fnt.BASIC_RECIPE}\n{fnt.HELP_POINTER}"
    assert fnt.FOOTER.count("\n") == 2


def test_footer_ends_with_canonical_help_pointer_sentence() -> None:
    assert fnt.FOOTER.endswith(
        "Run `yoke ouroboros field-note append --help` "
        "for the worked failure modes and decision tree."
    )


def test_footer_does_not_carry_old_cardinality_string() -> None:
    # The fixed-count cardinality string was retired in favor of a
    # cardinality-free phrase so the catalog can grow / shrink without
    # drifting the inline-short footer. Construct the retired literal
    # dynamically so the AC-1 obsoleted-terms grep stays clean.
    retired = " ".join(("7", "worked", "failure", "modes"))
    assert retired not in fnt.FOOTER


def test_failure_modes_exact_count() -> None:
    # 3 failed + 2 new + 2 unclear + 3 observation = 10 worked examples.
    assert len(fnt.FAILURE_MODES) == 10


def test_failure_modes_kind_distribution() -> None:
    counts: dict[str, int] = {kind: 0 for kind in _VALID_KINDS}
    for mode in fnt.FAILURE_MODES:
        counts[mode.kind] += 1
    assert counts == {"failed": 3, "new": 2, "unclear": 2, "observation": 3}


def test_failure_modes_are_named_tuples() -> None:
    for mode in fnt.FAILURE_MODES:
        assert isinstance(mode, fnt.FailureMode)


def test_failure_mode_kinds_are_valid_enum() -> None:
    for mode in fnt.FAILURE_MODES:
        assert mode.kind in _VALID_KINDS, (
            f"FailureMode {mode.title!r} kind={mode.kind!r} "
            f"not in {sorted(_VALID_KINDS)}"
        )


def test_failure_mode_fields_non_empty() -> None:
    for mode in fnt.FAILURE_MODES:
        assert mode.kind.strip(), mode
        assert mode.title.strip(), mode
        assert mode.example_evidence.strip(), mode
        assert mode.when_to_fire.strip(), mode


def test_failure_mode_titles_unique() -> None:
    titles = [mode.title for mode in fnt.FAILURE_MODES]
    assert len(set(titles)) == len(titles), titles


_PURE_DATA_NAMES = frozenset({
    "DIRECTIVE",
    "BASIC_RECIPE",
    "HELP_POINTER",
    "FOOTER",
    "KIND_VALUES",
    "KIND_OBSERVATION_DEFINITION",
    "FailureMode",
    "FAILURE_MODES",
    "HELP_BODY",
})


def test_pure_data_surface_remains_pure_data() -> None:
    # The directive constants and the FailureMode catalog must stay pure data
    # so consumers (lint footers, packet renderers, doctor HCs) never
    # accidentally pull in I/O. The pure renderer ``format_failure_modes_for_help``
    # is a deterministic string composer — it has no I/O, no globals, no
    # mutability — so it is allowed in __all__ alongside the constants.
    import inspect

    for name in _PURE_DATA_NAMES:
        value = getattr(fnt, name)
        if inspect.isfunction(value) or inspect.ismethod(value):
            raise AssertionError(
                f"field_note_text pure-data names must not be callable; "
                f"found {name!r}"
            )


def test_module_exports() -> None:
    assert set(fnt.__all__) == _PURE_DATA_NAMES | {"format_failure_modes_for_help"}


def test_format_failure_modes_for_help_includes_every_mode() -> None:
    rendered = fnt.format_failure_modes_for_help()
    for mode in fnt.FAILURE_MODES:
        assert mode.title in rendered, mode.title
        assert mode.example_evidence in rendered, mode.example_evidence
        assert mode.when_to_fire in rendered, mode.when_to_fire
        # Kind appears bracket-tagged in the rendered header line.
        assert f"[{mode.kind}]" in rendered, mode.kind


def test_format_failure_modes_for_help_includes_decision_tree_and_vocabulary() -> None:
    rendered = fnt.format_failure_modes_for_help()
    assert "Decision tree" in rendered
    assert "Canonical --kind vocabulary" in rendered
    # All four --kind enum values appear in the canonical vocabulary block.
    for kind in fnt.KIND_VALUES:
        assert kind in rendered


def test_format_failure_modes_for_help_decision_tree_branches_on_observation_first() -> None:
    rendered = fnt.format_failure_modes_for_help()
    # The decision tree's top branch now asks the bug-observation question first.
    assert "Did you observe a minor bug or surprise unrelated to current scope?" in rendered


def test_format_failure_modes_for_help_does_not_carry_old_cardinality() -> None:
    rendered = fnt.format_failure_modes_for_help()
    retired = " ".join(("7", "worked", "failure", "modes"))
    assert retired not in rendered


def test_format_failure_modes_for_help_references_all_four_kinds() -> None:
    rendered = fnt.format_failure_modes_for_help()
    for kind in fnt.KIND_VALUES:
        assert kind in rendered


def test_format_failure_modes_for_help_is_deterministic() -> None:
    # Pure renderer: same input -> same output, idempotent across calls.
    assert fnt.format_failure_modes_for_help() == fnt.format_failure_modes_for_help()


def test_help_body_names_both_scopes_in_preamble() -> None:
    # HELP_BODY's preamble must name both scopes the channel covers so the
    # operator reading `--help` understands the broadened surface.
    assert "Recipe gaps" in fnt.HELP_BODY
    assert "Minor bug observations" in fnt.HELP_BODY


def test_help_body_lists_exactly_four_kinds() -> None:
    # Each kind appears at least once in the rendered HELP_BODY.
    for kind in fnt.KIND_VALUES:
        assert kind in fnt.HELP_BODY, kind


def test_help_body_includes_decision_tree_with_observation_top_branch() -> None:
    assert "Decision tree" in fnt.HELP_BODY
    assert "Did you observe a minor bug or surprise unrelated to current scope?" in fnt.HELP_BODY


def test_help_body_includes_exactly_ten_worked_examples() -> None:
    # The catalog has 10 modes (3 failed / 2 new / 2 unclear / 3 observation);
    # HELP_BODY renders each as a numbered entry "N. [kind] Title".
    for idx, mode in enumerate(fnt.FAILURE_MODES, start=1):
        assert f"{idx}. [{mode.kind}] {mode.title}" in fnt.HELP_BODY


def test_help_body_observation_kind_appears_at_least_three_times() -> None:
    # 3 observation worked examples => HELP_BODY references [observation]
    # at least 3 times in numbered headers (plus once in vocabulary, etc.).
    assert fnt.HELP_BODY.count("[observation]") >= 3


def test_help_body_ends_with_inline_short_footer() -> None:
    assert fnt.HELP_BODY.endswith(fnt.FOOTER)


def test_help_body_does_not_carry_old_cardinality_string() -> None:
    retired = " ".join(("7", "worked", "failure", "modes"))
    assert retired not in fnt.HELP_BODY
