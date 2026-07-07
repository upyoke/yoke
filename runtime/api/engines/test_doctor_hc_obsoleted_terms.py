"""Tests for HC-obsoleted-terms residue checks and pre-existing pattern shape.

The current epic-link ontology pattern shape tests (SQL form, prose form, child-issue prose,
``type=issue with an epic parent``) live in
``test_doctor_hc_obsoleted_terms_patterns.py``. Scan-on-synthetic-tree and
HC-wiring tests live in ``test_doctor_hc_obsoleted_terms_scan.py``, except the
retired product-token fixtures below, which stay beside their residue and
shape tests.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from yoke_core.engines.doctor_hc_obsoleted_terms import (
    OBSOLETED_TERM_PATTERNS,
    OBSOLETED_TERM_LABELS,
    scan_repo,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Cannot locate repo root")


REPO = _repo_root()


# ---------------------------------------------------------------------------
# Residue checks — AC-21 + Pass 3 residue requirements
# ---------------------------------------------------------------------------


def _run_git_grep(pattern: str) -> list[str]:
    """Return lines where *pattern* matches any tracked file in the repo.

    Uses ``git grep`` so the scan is limited to tracked content (honouring
    ``.gitignore``) and restricted to the current tree rather than working
    directory scratch state. Output is ``path:line: content``.
    """
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "-E", pattern],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:  # pragma: no cover — git always present in CI
        pytest.skip("git not available for residue check")
    if result.returncode not in (0, 1):  # 1 == no matches
        pytest.fail(f"git grep failed: {result.stderr}")
    return [line for line in result.stdout.splitlines() if line]


def _filter_tolerated(lines: list[str], *, allow_path_substrings: tuple[str, ...]) -> list[str]:
    """Drop lines that match any of the allowed path substrings.

    The HC file itself declares the patterns as escaped regex, which the
    residue greps cannot match in their bare symbol form. Other residue paths
    must be zero.
    """
    out: list[str] = []
    for line in lines:
        path = line.split(":", 1)[0]
        if any(sub in path for sub in allow_path_substrings):
            continue
        out.append(line)
    return out


# The HC itself, its test companion, and a small set of enforcement /
# historical-audit surfaces are the authorized locations for naming the
# obsoleted terms. The HC's OBSOLETED_TERM_LABELS has to reference the bare
# term to be useful; the enforcement code that parses legacy command shapes
# (``observe.py``'s cmdline regexes, the ``lint_sqlite_rules*`` siblings'
# command-text lint) needs the literal name; the shell-inventory ledger and
# zero-shell audit legitimately enumerate retired script names. Every other
# live path must stay clean.
_AUTHORIZED_DECLARATION_PATHS: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms_allowlists.py",
    "runtime/api/engines/doctor_hc_obsoleted_terms.py",
    "runtime/api/engines/doctor_hc_obsoleted_terms_allowlists.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_scan.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_patterns.py",
    "runtime/api/domain/observe.py",
    "runtime/api/domain/lint_sqlite_rules.py",
    "runtime/api/domain/lint_sqlite_rules_columns.py",
    "runtime/api/domain/lint_sqlite_rules_guards.py",
    "runtime/api/domain/lint_sqlite_rules_lifecycle.py",
    "runtime/api/domain/lint_sqlite_rules_operators.py",
    "runtime/api/domain/lint_sqlite_rules_preprocess.py",
    "runtime/api/domain/test_lint_sqlite_cmd.py",
    "runtime/api/tools/shell_inventory.py",
    "runtime/api/tools/shell_inventory_classify.py",
    "runtime/api/tools/shell_inventory_report.py",
    "runtime/api/tools/shell_inventory_rules.py",
    "runtime/api/tools/shell_inventory_scan.py",
    "runtime/api/tools/shell_inventory_closeout.py",
    "packages/yoke-core/src/yoke_core/domain/runs.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_agents_prompts.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_classify.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_report.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_rules.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_scan.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_closeout.py",
    "runtime/api/test_zero_shell_proof.py",
    "runtime/api/test_zero_shell_proof_test_helpers.py",
    "ouroboros/",
    "docs/archive/",
    "docs/archive/legacy-plan-artifacts/",
)


def _retired_parent_epic_symbol() -> str:
    return "items" + "." + "epic"


def _retired_parent_epic_symbol_pattern() -> str:
    return r"items" + r"\." + "epic"


def _retired_parent_epic_cli_pattern() -> str:
    return r"items\s+(get|update|set)\s+\S+\s+" + "epic" + r"\b"


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


def test_items_epic_has_no_live_residue():
    """AC-21: the retired parent-epic item field must not appear in any tracked
    file outside the authorized declaration path(s)."""
    hits = _run_git_grep(_retired_parent_epic_symbol_pattern())
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "retired parent-epic item field must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_items_get_update_epic_cli_form_has_no_live_residue():
    """AC-R4/AC-R5: the retired parent-epic item field also leaked in
    CLI-argument form. The pattern tightening catches this form; the live tree
    must be clean before the lint ships.

    The git-grep pattern uses ERE-portable alternatives to ``\\b`` so the
    field token must be followed by end-of-line or a non-word-character.
    """
    hits = _run_git_grep(r"items (get|update|set) +[^ ]+ +epic($|[^a-zA-Z0-9_])")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "retired parent-epic item field CLI form must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_yoke_core_domain_doctor_has_no_live_residue():
    """Pass 3 residue check: ``yoke_core.domain.doctor`` does not exist and must
    not appear in live tracked files outside the authorized declaration paths."""
    hits = _run_git_grep(r"yoke_core\.domain\.doctor")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "yoke_core.domain.doctor must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_yoke_db_sh_has_no_live_prose_residue():
    """Pass 3 residue check applied to the AC-8 prose surface.

    ``yoke-db.sh`` is retired. It must not appear in live operator-facing
    prose — doctrine, docs, or skill bodies — outside the authorized
    declaration sites. Parser test data, lint rules that still detect
    historical command shapes, and enforcement code that names the retired
    wrapper for discovery are tolerated via ``_AUTHORIZED_DECLARATION_PATHS``
    because they are enforcement/audit infrastructure, not surfaces that
    teach the retired name to a reader.
    """
    hits = _run_git_grep(r"yoke-db\.sh")
    tolerated_paths = _AUTHORIZED_DECLARATION_PATHS + (
        # Enforcement + audit code that legitimately names the retired wrapper
        # for parser/detector purposes. These are not operator-facing prose.
        "runtime/api/domain/runs.py",
        "runtime/api/domain/agent_stop_test_helpers.py",
        "runtime/api/domain/test_agent_stop.py",
        "runtime/api/domain/test_browser_qa.py",
        "runtime/api/domain/test_lint_sqlite_cmd_columns.py",
        "runtime/api/domain/test_lint_sqlite_cmd_guards.py",
        "runtime/api/domain/test_lint_sqlite_cmd_lifecycle.py",
        "runtime/api/domain/test_lint_sqlite_cmd_operators.py",
        "runtime/api/domain/test_lint_tc_label.py",
        "runtime/api/engines/doctor_hc_agents_prompts.py",
        "runtime/api/engines/test_doctor_filesystem_full.py",
        "runtime/api/engines/test_doctor_filesystem_full_repo.py",
        "runtime/api/engines/test_doctor_hc_obsoleted_terms_scan.py",
        "runtime/api/test_observe_full_refs.py",
        "runtime/api/test_skill_doc_regressions_conduct_simulation.py",
    )
    tolerated = _filter_tolerated(hits, allow_path_substrings=tolerated_paths)
    assert not tolerated, (
        "yoke-db.sh must not appear in operator-facing prose.\n"
        + "\n".join(tolerated[:20])
    )


def test_retired_product_name_has_no_live_residue():
    """The retired product name belongs only in archive/audit surfaces."""
    hits = _run_git_grep(r"\b[Ss]unday\b")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "retired product name must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_retired_product_domain_token_has_no_live_residue():
    """The retired product domain token belongs only in archive/audit surfaces."""
    hits = _run_git_grep(r"[Ss]unday[Dd]o")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "retired product domain token must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_retired_item_prefix_has_no_live_residue():
    """The retired item prefix belongs only in archive/audit surfaces."""
    hits = _run_git_grep(r"\bSUN-[0-9]+\b")
    tolerated = _filter_tolerated(hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS)
    assert not tolerated, (
        "retired item prefix must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_agents_md_does_not_announce_items_epic_retirement():
    """Pass 3: the retirement-announcement sentence in AGENTS.md is itself
    cruft and must be gone. The schema is the source of truth; live prose must
    not teach the retired field name."""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert _retired_parent_epic_symbol() not in text, (
        "AGENTS.md must not name the retired parent-epic item field. Let the "
        "schema speak for itself."
    )


# ---------------------------------------------------------------------------
# Pattern storage shape — AC-21 robustness
# ---------------------------------------------------------------------------


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
        r"yoke_core\.domain\.doctor": "yoke_core.domain.doctor",
        r"yoke-db\.sh": "yoke-db.sh",
        r"\b[Ss]unday\b": "Sunday",
        r"(?i)\b[s]undaydo\b": "sundaydo",
        r"\bSUN-\d+\b": "SUN-123",
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
    compiled = re.compile(r"(?i)\b[s]undaydo\b")
    for line in [
        "sundaydo",
        "Sundaydo was the working name.",
        "SUNDAYDO",
        "https://api.sundaydo.com/install",
        "curl https://www.sundaydo.com/",
    ]:
        assert compiled.search(line), f"expected domain-token match on: {line!r}"


def test_product_domain_pattern_does_not_match_adjacent_words():
    """Token boundaries must keep embeddings and split words from triggering."""
    compiled = re.compile(r"(?i)\b[s]undaydo\b")
    for line in [
        "sundaydose",
        "asundaydo",
        "sunday do the deploy",
    ]:
        assert not compiled.search(line), f"unexpected domain-token match on: {line!r}"


def test_item_prefix_pattern_is_anchored():
    """The retired item prefix matches only the uppercase digit-suffixed id
    shape, never fragments or embeddings."""
    compiled = re.compile(r"\bSUN-\d+\b")
    for line in ["SUN-123", "Imported from (SUN-42).", "see SUN-7,"]:
        assert compiled.search(line), f"expected item-prefix match on: {line!r}"
    for line in ["SUN-", "SUN-abc", "K8SUN-12", "SUN-123x", "sun-123"]:
        assert not compiled.search(line), f"unexpected item-prefix match on: {line!r}"


# ---------------------------------------------------------------------------
# Fixture-tree scans — retired product token patterns
# ---------------------------------------------------------------------------


def test_scan_flags_retired_domain_token_in_url(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "stale_domain.md").write_text(
        "Old installer: https://api." + "sunday" + "do" + ".com/install\n"
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
        assert not compiled.search(line), f"unexpected match on prose/placeholder: {line!r}"
