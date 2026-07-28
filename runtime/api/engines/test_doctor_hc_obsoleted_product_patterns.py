"""Pattern-shape and synthetic-scan tests for retired product tokens."""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_hc_obsoleted_terms import (
    OBSOLETED_TERM_LABELS,
    OBSOLETED_TERM_PATTERNS,
    scan_repo,
)
from .test_doctor_hc_obsoleted_terms import (
    REPO,
    _db_router_items_cmd,
    _retired_parent_epic_cli_pattern,
    _retired_parent_epic_symbol,
    _retired_parent_epic_symbol_pattern,
)

_RETIRED_PRODUCT_NAME = "sun" + "day"
_RETIRED_PRODUCT_DOMAIN = _RETIRED_PRODUCT_NAME + "do"
_RETIRED_ITEM_PREFIX = "SU" + "N"
_RETIRED_WORK_ITEM_SYNONYM = "tick" + "et"


def test_patterns_stored_as_escaped_regex():
    """Every pattern in :data:`OBSOLETED_TERM_PATTERNS` must contain a regex
    escape so a naive residue grep for the bare term does not match the pattern
    declaration itself."""
    for pat in OBSOLETED_TERM_PATTERNS:
        assert "\\" in pat, f"pattern {pat!r} must contain a regex escape"


def test_every_pattern_has_a_label():
    for pat in OBSOLETED_TERM_PATTERNS:
        assert pat in OBSOLETED_TERM_LABELS, (
            f"OBSOLETED_TERM_LABELS missing entry for {pat!r}"
        )


def test_patterns_compile_and_match_bare_term():
    """Sanity check: compiled regex matches the intended bare term."""
    expected = {
        _retired_parent_epic_symbol_pattern(): _retired_parent_epic_symbol(),
        _retired_parent_epic_cli_pattern(): _db_router_items_cmd("get", "5", "epic"),
        r"yoke_core\.domain\." + "doctor": "yoke_core.domain." + "doctor",
        r"yoke-" + r"db\.sh": "yoke-" + "db.sh",
        r"\b[Ss]" + r"unday\b": _RETIRED_PRODUCT_NAME.title(),
        r"(?i)\b[s]" + r"undaydo\b": _RETIRED_PRODUCT_DOMAIN,
        r"\bSU" + r"N-\d+\b": f"{_RETIRED_ITEM_PREFIX}-123",
        r"\byoke_core\.domain\.qa_requirements_"
        + r"auto\b": "yoke_core.domain.qa_requirements_" + "auto",
        r"\bqa\.requirement\.auto_create_for_"
        + r"item\b": "qa.requirement.auto_create_for_" + "item",
        r"\byoke\s+qa\s+requirement\s+auto-create-for-"
        + r"item\b": "yoke qa requirement auto-create-for-" + "item",
        r"\b" + "tick" + r"ets?\b": _RETIRED_WORK_ITEM_SYNONYM,
    }
    for pat, sample in expected.items():
        assert re.compile(pat).search(sample), (
            f"pattern {pat!r} should match bare text {sample!r}"
        )


def test_cli_form_pattern_matches_expected_shapes():
    """The CLI-form pattern must catch every skill-prose shape that reads or
    writes the retired parent-epic item field, across the placeholder
    conventions the skill library uses (``{N}``, ``${N}``, bare integer)."""
    compiled = re.compile(_retired_parent_epic_cli_pattern())
    for line in [
        _db_router_items_cmd("get", "{N}", "epic"),
        _db_router_items_cmd("get", "5", "epic"),
        _db_router_items_cmd("get", "${N}", "epic"),
        _db_router_items_cmd("update", "{N}", "epic", "{epic-id}"),
    ]:
        assert compiled.search(line), f"expected CLI-form match on: {line!r}"


def test_cli_form_pattern_does_not_match_adjacent_fields():
    """Word-boundary on the field token must keep adjacent names from
    triggering a false positive."""
    compiled = re.compile(_retired_parent_epic_cli_pattern())
    for line in [
        "items get {N} epic_id",
        "items get {N} epic_tasks_count",
        "items update 5 epic_parent_id 42",
    ]:
        assert not compiled.search(line), f"unexpected CLI-form match on: {line!r}"


def test_product_domain_pattern_matches_token_and_url_casings():
    """The domain token is a compound the bare product-name boundary cannot
    reach — bare tokens, mixed casings, and URL hosts must all match."""
    compiled = re.compile(r"(?i)\b[s]" + r"undaydo\b")
    for line in [
        _RETIRED_PRODUCT_DOMAIN,
        f"{_RETIRED_PRODUCT_DOMAIN.title()} was the working name.",
        _RETIRED_PRODUCT_DOMAIN.upper(),
        f"https://api.{_RETIRED_PRODUCT_DOMAIN}.com/install",
        f"curl https://www.{_RETIRED_PRODUCT_DOMAIN}.com/",
    ]:
        assert compiled.search(line), f"expected domain-token match on: {line!r}"


def test_product_domain_pattern_does_not_match_adjacent_words():
    """Token boundaries must keep embeddings and split words from triggering."""
    compiled = re.compile(r"(?i)\b[s]" + r"undaydo\b")
    for line in [
        _RETIRED_PRODUCT_DOMAIN + "se",
        "a" + _RETIRED_PRODUCT_DOMAIN,
        _RETIRED_PRODUCT_NAME + " do the deploy",
    ]:
        assert not compiled.search(line), f"unexpected domain-token match on: {line!r}"


def test_item_prefix_pattern_is_anchored():
    """The retired item prefix matches only the uppercase digit-suffixed id
    shape, never fragments or embeddings."""
    compiled = re.compile(r"\bSU" + r"N-\d+\b")
    for line in [
        f"{_RETIRED_ITEM_PREFIX}-123",
        f"Imported from ({_RETIRED_ITEM_PREFIX}-42).",
        f"see {_RETIRED_ITEM_PREFIX}-7,",
    ]:
        assert compiled.search(line), f"expected item-prefix match on: {line!r}"
    for line in [
        f"{_RETIRED_ITEM_PREFIX}-",
        f"{_RETIRED_ITEM_PREFIX}-abc",
        f"K8{_RETIRED_ITEM_PREFIX}-12",
        f"{_RETIRED_ITEM_PREFIX}-123x",
        f"{_RETIRED_ITEM_PREFIX.lower()}-123",
    ]:
        assert not compiled.search(line), f"unexpected item-prefix match on: {line!r}"


# ---------------------------------------------------------------------------
# Fixture-tree scans — retired product token patterns
# ---------------------------------------------------------------------------


def test_scan_flags_retired_domain_token_in_url(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_domain.md").write_text(
        "Old installer: https://api." + "sun" + "day" + "do" + ".com/install\n"
    )
    hits = scan_repo(tmp_path)
    assert any("retired product domain token" in h for h in hits), hits


def test_scan_flags_retired_item_prefix_in_doc(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_prefix.md").write_text(
        "Imported from " + "SUN-" + "1234" + " before the backlog rename.\n"
    )
    hits = scan_repo(tmp_path)
    assert any("retired item prefix" in h for h in hits), hits


def test_scan_flags_retired_work_item_synonym_in_live_prose(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_work_item_name.md").write_text(
        "File a " + _RETIRED_WORK_ITEM_SYNONYM + " for this change.\n"
    )
    hits = scan_repo(tmp_path)
    assert any("retired work-item synonym" in h for h in hits), hits


def test_scan_ignores_retired_work_item_synonym_in_strategy_evidence(
    tmp_path: Path,
):
    strategy = tmp_path / ".yoke" / "strategy"
    strategy.mkdir(parents=True)
    (strategy / "PLAN.md").write_text(
        "Future " + _RETIRED_WORK_ITEM_SYNONYM + " candidates.\n"
    )

    assert scan_repo(tmp_path) == []


def test_live_tree_clean_for_retired_product_token_patterns():
    """The HC's tree scan finds zero hits for the retired product domain
    token and item-prefix patterns on the live tree. Scoped by label so
    residue for OTHER patterns (owned by whichever change introduces it)
    cannot mask this pattern family's verdict."""
    hits = scan_repo(REPO)
    flagged = [
        h
        for h in hits
        if "retired product domain token" in h or "retired item prefix" in h
    ]
    assert flagged == [], (
        "retired product token patterns must find no live-tree residue.\n"
        + "\n".join(flagged[:20])
    )


def test_cli_form_pattern_does_not_match_prose_or_placeholders():
    """Prose lines that happen to mention the command verb and the retired
    field in separate clauses must not match — neither must placeholder uses
    that embed the field token inside the ID placeholder."""
    compiled = re.compile(_retired_parent_epic_cli_pattern())
    for line in [
        # Prose from conduct/error-handling.md:46 — two separate clauses.
        (
            "Issue items use `items update` for status, and Epic items use "
            "`items update` for task-level status."
        ),
        # Placeholder use from amend/SKILL.md — the field token is inside the ID.
        "python3 -m yoke_core.cli.db_router items get {epic-YOK-N} worktree_plan",
        # Backtick immediately after the command breaks the whitespace contract.
        "Issue items use `python3 -m yoke_core.cli.db_router items update`",
    ]:
        assert not compiled.search(line), (
            f"unexpected match on prose/placeholder: {line!r}"
        )
