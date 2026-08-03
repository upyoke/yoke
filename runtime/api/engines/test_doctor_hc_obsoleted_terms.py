"""Tests for HC-obsoleted-terms residue checks and pre-existing pattern shape.

The current epic-link ontology pattern shape tests (SQL form, prose form, child-issue prose,
``type=issue with an epic parent``) live in
``test_doctor_hc_obsoleted_terms_patterns.py``. Scan-on-synthetic-tree and
HC-wiring tests live in ``test_doctor_hc_obsoleted_terms_scan.py``, except the
retired product-token fixtures below, which stay beside their residue and
shape tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Cannot locate repo root")


REPO = _repo_root()


# ---------------------------------------------------------------------------
# Residue checks — retired terms must not survive in live tracked files
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


def _filter_tolerated(
    lines: list[str], *, allow_path_substrings: tuple[str, ...]
) -> list[str]:
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
# (``observe.py``'s cmdline regexes, the ``lint_db_rules*`` siblings'
# command-text lint) needs the literal name; the zero-shell audit legitimately
# enumerates retired script names. Every other
# live path must stay clean.
_AUTHORIZED_DECLARATION_PATHS: tuple[str, ...] = (
    # Project-local health checks: the scanner declares the retired terms it
    # hunts for, and the agent-prompt detector names the retired command
    # shape it looks for in tracked prompts.
    ".yoke/doctor/check_obsoleted_terms.py",
    # The catalogue holds the retired names the scanner hunts for; it
    # declares them rather than leaking them.
    ".yoke/doctor/_obsoleted_terms_catalog.py",
    ".yoke/doctor/check_agents_prompts.py",
    "packages/yoke-core/src/yoke_core/engines/check_obsoleted_terms.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms_allowlists.py",
    "runtime/api/engines/check_obsoleted_terms.py",
    "runtime/api/engines/doctor_hc_obsoleted_terms_allowlists.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_scan.py",
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_patterns.py",
    "runtime/api/domain/observe.py",
    "runtime/api/domain/lint_db_rules.py",
    "runtime/api/domain/lint_db_rules_columns.py",
    "runtime/api/domain/lint_db_rules_guards.py",
    "runtime/api/domain/lint_db_rules_lifecycle.py",
    "runtime/api/domain/lint_db_rules_operators.py",
    "runtime/api/domain/lint_db_rules_preprocess.py",
    "runtime/api/domain/test_lint_db_cmd.py",
    "packages/yoke-core/src/yoke_core/domain/runs.py",
    "packages/yoke-core/src/yoke_core/engines/check_agents_prompts.py",
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
    """The retired parent-epic item field must not appear in any tracked
    file outside the authorized declaration path(s)."""
    hits = _run_git_grep(_retired_parent_epic_symbol_pattern())
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
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
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
    assert not tolerated, (
        "retired parent-epic item field CLI form must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_yoke_core_domain_doctor_has_no_live_residue():
    """Pass 3 residue check: ``yoke_core.domain.doctor`` does not exist and must
    not appear in live tracked files outside the authorized declaration paths."""
    hits = _run_git_grep(r"yoke_core\.domain\.doctor")
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
    assert not tolerated, (
        "yoke_core.domain.doctor must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_yoke_db_sh_has_no_live_prose_residue():
    """Residue check applied to the operator-facing prose surface.

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
        # The timing profile stores collected node ids, including parameterized
        # parser fixtures that intentionally exercise the retired command shape.
        ".test_durations",
        "runtime/api/domain/runs.py",
        "runtime/api/domain/agent_stop_test_helpers.py",
        "runtime/api/domain/test_agent_stop.py",
        "runtime/api/domain/test_browser_qa.py",
        "runtime/api/domain/test_lint_db_cmd_columns.py",
        "runtime/api/domain/test_lint_db_cmd_guards.py",
        "runtime/api/domain/test_lint_db_cmd_lifecycle.py",
        "runtime/api/domain/test_lint_db_cmd_operators.py",
        "runtime/api/domain/test_lint_tc_label.py",
        "runtime/api/engines/check_agents_prompts.py",
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
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
    assert not tolerated, (
        "retired product name must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_retired_product_domain_token_has_no_live_residue():
    """The retired product domain token belongs only in archive/audit surfaces."""
    hits = _run_git_grep(r"[Ss]unday[Dd]o")
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
    assert not tolerated, (
        "retired product domain token must not appear in live tracked files.\n"
        + "\n".join(tolerated[:20])
    )


def test_retired_item_prefix_has_no_live_residue():
    """The retired item prefix belongs only in archive/audit surfaces."""
    hits = _run_git_grep(r"\bSUN-[0-9]+\b")
    tolerated = _filter_tolerated(
        hits, allow_path_substrings=_AUTHORIZED_DECLARATION_PATHS
    )
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
