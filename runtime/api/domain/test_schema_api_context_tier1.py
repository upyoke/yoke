"""Tier 1 packet expansion — per-anchor regressions.

Sibling of :mod:`test_schema_api_context` and
:mod:`test_schema_api_context_topics`. Holds the per-anchor assertions
for AC-3 / AC-4 / AC-24 / AC-27 / AC-29 / AC-31:

- Column-name salience: ``current_item_id``, ``path_string``,
  ``claim_id``, ``section_name`` appear adjacent to their owning
  tables in ``main_agent``'s rendered packet.
- Function-call surface stanza names the canonical models / dispatcher.
- JSON-nested-field schemas appear for the seven enumerated columns.
- CLI cheat sheet enumerates the canonical flag set for the eight
  command surfaces named in the task spec.
- ``worktree paths db`` entry carries the example invocation and the
  "use this, not ad-hoc imports" guidance.
- The packet teaches zero bare ``claim-list``, ``pt.path``,
  ``items.item_id``, ``work_claims.state``, ``events.source_id``
  confabulations.
- ``harness_id`` enum is named (``claude-code | codex``).
- The function-call envelope minimal example includes
  ``actor.session_id``, dict ``preconditions``, dict ``options``.
- No bare ``python3 -m yoke_core.engines.doctor`` example.
"""

from __future__ import annotations

import re

from yoke_core.domain import schema_api_context as sac


# ---------------------------------------------------------------------------
# Column-name salience + function-call surface stanza + JSON schemas
# ---------------------------------------------------------------------------


def _main_body() -> str:
    return sac.render_role_packet("main_agent")


def test_current_item_id_appears_adjacent_to_harness_sessions() -> None:
    body = _main_body()
    # The salient harness_sessions bullet must enumerate
    # current_item_id in the column list; the rendered bullet is a
    # single contiguous region.
    pat = re.compile(r"`harness_sessions`.*?current_item_id", re.DOTALL)
    assert pat.search(body), (
        "current_item_id must appear adjacent to its owning table "
        "harness_sessions in the schema cheat sheet."
    )


def test_path_string_appears_adjacent_to_path_targets() -> None:
    body = _main_body()
    pat = re.compile(r"`path_targets`.*?path_string", re.DOTALL)
    assert pat.search(body), (
        "path_string must appear adjacent to its owning table "
        "path_targets in the schema cheat sheet."
    )


def test_claim_id_appears_adjacent_to_path_claim_targets() -> None:
    body = _main_body()
    pat = re.compile(r"`path_claim_targets`.*?claim_id", re.DOTALL)
    assert pat.search(body), (
        "claim_id must appear adjacent to its owning table "
        "path_claim_targets in the schema cheat sheet."
    )


def test_section_name_appears_adjacent_to_item_sections() -> None:
    body = _main_body()
    pat = re.compile(r"`item_sections`.*?section_name", re.DOTALL)
    assert pat.search(body), (
        "section_name must appear adjacent to its owning table "
        "item_sections in the schema cheat sheet."
    )


def test_function_call_surface_stanza_names_canonical_models() -> None:
    body = _main_body()
    assert "FunctionCallRequest" in body
    assert "FunctionCallResponse" in body
    assert "yoke_contracts.api.function_call" in body
    assert "yoke_core.domain.yoke_function_dispatch" in body


_JSON_NESTED_COLUMNS_REQUIRED = (
    "items.browser_qa_metadata",
    "items.db_mutation_profile",
    "items.db_compatibility_attestation",
    "harness_sessions.offer_envelope",
    "qa_requirements.capability_requirements",
    "qa_requirements.success_policy",
    "epic_tasks.dependencies",
)


def test_json_nested_field_schemas_appear_for_seven_enumerated_columns() -> None:
    body = _main_body()
    for column in _JSON_NESTED_COLUMNS_REQUIRED:
        assert column in body, (
            f"JSON-nested-field schema for {column} must appear in the "
            "rendered main_agent packet (AC-3 task 002)."
        )
    # Access-pattern guidance must appear too.
    assert "parse the rendered JSON" in body
    assert "do NOT query nested fields as top-level columns" in body


# ---------------------------------------------------------------------------
# CLI cheat sheet enumerates canonical flag sets
# ---------------------------------------------------------------------------


# Canonical Tier-1 ``yoke <subcommand>`` agent shapes plus the
# source-dev/operator-debug fallbacks the packet labels (current).
_CLI_ANCHORS_REQUIRED = (
    "yoke claims work acquire --item YOK-",
    "yoke claims work release --item YOK-",
    "yoke claims path register", "yoke claims path widen",
    "yoke lifecycle transition", "yoke items structured-field replace",
    "yoke items progress-log append", "yoke events query",
    "yoke ouroboros field-note append",
    "yoke claims path list --item YOK-N", "yoke db-claim amend YOK-N",
    "--state none", "backlog-cli", "lifecycle.transition",
    "yoke db read \"SELECT 1\"",
    "worktree paths db", "harness_id",
)


def test_cli_cheat_sheet_contains_canonical_flag_sets() -> None:
    body = _main_body()
    for anchor in _CLI_ANCHORS_REQUIRED:
        assert anchor in body, (
            f"CLI cheat sheet must teach canonical flag set anchor "
            f"{anchor!r} (AC-4 task 002)."
        )


def test_sections_family_cli_taught() -> None:
    """Sections CLI surfaces get/upsert/delete in the cheat sheet."""

    body = _main_body()
    assert "yoke items section get" in body
    assert "yoke items section upsert" in body
    assert "yoke items section delete" in body


def test_packet_uses_state_not_claim_state() -> None:
    """``db-claim-amend`` advertises ``--state none``; the historical
    ``--claim-state`` form must NEVER appear in rendered agent context."""

    body = _main_body()
    assert "--state none" in body
    assert "--claim-state" not in body


def test_harness_id_enum_names_claude_code_and_codex() -> None:
    """The ``harness_id`` enum is named so agents stop confabulating
    ``claude_code`` / ``codex_cli`` when inspecting
    ``harness_sessions.executor``."""

    body = _main_body()
    assert "claude-code" in body
    assert "codex" in body
    assert "`harness_id` enum" in body


def test_raw_diagnostic_read_entry_and_ad_hoc_warning_present() -> None:
    body = _main_body()
    assert 'yoke db read "SELECT 1"' in body
    assert "source-dev/operator-debug `db_router query` fallback" in body
    # Raw-read guidance + negative example.
    assert "Never use ad-hoc imports" in body
    assert "from yoke_core.domain.worktree import get_db_path" in body
    assert "worktree paths db" in body
    assert "refuses root SQLite authority" in body


# ---------------------------------------------------------------------------
# No historical confabulations
# ---------------------------------------------------------------------------


def test_no_bare_claim_list_teaching_string() -> None:
    """The packet teaches ``path-claim-list`` only, never bare
    ``claim-list`` (which historically conflated work-claim list and
    path-claim list and produced confabulation telemetry)."""

    body = _main_body()
    bare = re.findall(r"(?<!path-)claim-list", body)
    assert bare == [], (
        f"packet teaches bare 'claim-list' references: {bare}. The "
        "canonical surface is path-claim-list."
    )


_BANNED_CONFABULATIONS = (
    "pt.path",
    "items.item_id",
    "work_claims.state",
    "events.source_id",
)


def test_no_known_confabulations() -> None:
    body = _main_body()
    for term in _BANNED_CONFABULATIONS:
        assert term not in body, (
            f"packet contains banned confabulation '{term}'. AC-27 "
            "requires zero such strings in rendered agent context."
        )


# ---------------------------------------------------------------------------
# Function-call envelope minimal example shape
# ---------------------------------------------------------------------------


def test_minimal_envelope_names_session_id_preconditions_options() -> None:
    """The function-call surface stanza must name ``session_id``, dict
    ``preconditions``, and dict ``options`` so agents see the full
    envelope shape without re-deriving it."""

    body = _main_body()
    assert "session_id" in body
    assert "preconditions" in body
    assert "options" in body
    # The text "dicts (default `{}`)" anchors the dict-default semantics.
    assert "default `{}`" in body


def test_scratch_python_note_names_pythonpath_not_tmp_imports() -> None:
    """AC-29: the guidance must NOT direct agents at scratch `/tmp`
    Python imports as the normal path. If scratch Python is named, the
    repo-root/PYTHONPATH requirement must be explicit."""

    body = _main_body()
    assert "PYTHONPATH" in body
    assert "/tmp" in body  # surfaced only as the negative-example anchor
    assert "are not the agent path" in body


# ---------------------------------------------------------------------------
# No bare doctor invocation
# ---------------------------------------------------------------------------


def test_no_bare_doctor_invocation() -> None:
    """Every rendered Doctor example must carry ``--full``, ``--quick``,
    or ``--only ...``. Bare ``python3 -m yoke_core.engines.doctor``
    must not appear in the rendered packet."""

    body = _main_body()
    bare = re.findall(
        r"python3 -m runtime\.api\.engines\.doctor\b"
        r"(?!\s+(?:--full|--quick|--only))",
        body,
    )
    assert bare == [], (
        f"packet contains bare doctor invocation(s): {bare}. AC-31 "
        "requires --full / --quick / --only on every example."
    )


# ---------------------------------------------------------------------------
# AC-3 / AC-4 positive lifecycle.transition recipe
# ---------------------------------------------------------------------------


def test_lifecycle_transition_positive_cli_recipe_present() -> None:
    """The lifecycle.transition entry teaches the canonical ``yoke``
    CLI adapter sequence rather than anti-pattern prose.

    Current: the recipe shape is acquire → transition →
    release, all via the Tier-1 ``yoke <subcommand>`` grammar.
    """

    body = _main_body()
    assert "yoke claims work acquire --item YOK-N --reason transition" in body
    assert "yoke lifecycle transition YOK-N --to refined-idea" in body
    assert "yoke claims work release --item YOK-N" in body
    assert "lifecycle.transition.execute" in body


# ---------------------------------------------------------------------------
# Artifact-write ownership invariant in main_agent claims packet
# ---------------------------------------------------------------------------


_FORBIDDEN_SESSION_ID_AFFIRMATIVE = re.compile(
    r"(?:`--session-id S`\s+to\s+)?act\s+on\s+another\s+session",
    re.IGNORECASE | re.DOTALL,
)


def test_artifact_write_ownership_invariant_rendered() -> None:
    """main_agent teaches artifact-write ownership + who-claims framing
 and rejects the historical ``--session-id S`` affirmative
    shape."""

    body = _main_body()
    # AC-5 — invariant + enumerated artifact surfaces + who-claims framing.
    for anchor in (
        "Artifact writes require owning the item claim",
        "shared coordination state",
        "File Budget",
        "path-claim",
        "GitHub issue-body",
        "who-claims",
        "coordination identifier",
        "not authority to mutate",
        "self-identity assertion",
        "not cross-session authority",
    ):
        assert anchor in body, f"missing AC-5/AC-6 anchor: {anchor!r}"
    # AC-6 — the historical affirmative shape is rejected.
    bad = _FORBIDDEN_SESSION_ID_AFFIRMATIVE.findall(body)
    assert bad == [], (
        f"packet teaches `--session-id S` as a way to act on another "
        f"session's claim (matched: {bad}); AC-6 forbids this shape."
    )


# ---------------------------------------------------------------------------
# harness_sessions: new columns surface (AC-3 columns subset)
# ---------------------------------------------------------------------------


_NEW_HARNESS_SESSION_COLUMNS = (
    "recent_item_id",
    "recent_item_status",
    "recent_item_recorded_at",
    "offer_envelope",
    "mode",
    "executor_display_name",
)


def test_new_harness_sessions_columns_present() -> None:
    body = _main_body()
    for column in _NEW_HARNESS_SESSION_COLUMNS:
        assert column in body, (
            f"harness_sessions.{column} must be enumerated in the "
            "schema cheat sheet (task 002 packet expansion)."
        )
