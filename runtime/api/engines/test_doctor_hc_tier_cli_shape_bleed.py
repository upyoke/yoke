"""Unit tests for HC-tier-cli-shape-bleed."""

from __future__ import annotations

import pytest

from yoke_project_checks import check_tier_cli_shape_bleed as mod
from yoke_project_checks.check_tier_cli_shape_bleed import HC_SLUG
from .doctor_hc_tier_cli_shape_test_support import (
    _detail,
    _run,
    _setup,
    conn as conn,
)


def test_check_a_drifted_flag_in_tier5_fires(tmp_path, monkeypatch, conn):
    """`db-claim-amend --claim-state none` (real flag is `--state`) fires."""
    rel = ".agents/skills/yoke/conduct/SKILL.md"
    body = "    python3 -m yoke_core.api.service_client db-claim-amend --claim-state none\n"
    help_stdout = "usage: db-claim-amend --item ITEM --reason REASON [--state {none}]\n"
    _setup(
        tmp_path,
        monkeypatch,
        {rel: body},
        {rel: 5},
        {("yoke_core.api.service_client", "db-claim-amend"): (0, help_stdout)},
    )
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "`--claim-state`" in _detail(rec)
    assert HC_SLUG == rec.results[0].check_id


# --- Check B: bare Doctor scope --------------------------------------------
def test_check_b_bare_doctor_in_tier0_fires(tmp_path, monkeypatch, conn):
    rel = "AGENTS.md"
    body = "# Substrate\n\n$ python3 -m yoke_core.engines.doctor\n"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 0})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "bare" in _detail(rec)


def test_check_b_scoped_doctor_passes(tmp_path, monkeypatch, conn):
    rel = "AGENTS.md"
    body = "$ python3 -m yoke_core.engines.doctor --only foo\n"
    _setup(
        tmp_path,
        monkeypatch,
        {rel: body},
        {rel: 0},
        {("yoke_core.engines.doctor", None): (0, "usage: doctor [--only NAME]\n")},
    )

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_check_b_mid_prose_doctor_passes(tmp_path, monkeypatch, conn):
    """Mid-sentence Doctor mention (no SOL anchor, no shell prompt) passes."""
    rel = "docs/OVERVIEW.md"
    body = "Use python3 -m yoke_core.engines.doctor for health checks.\n"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_check_b_anti_pattern_marker_passes(tmp_path, monkeypatch, conn):
    rel = ".yoke/docs/lifecycle.md"
    body = "Anti-pattern: $ python3 -m yoke_core.engines.doctor\n"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_anchored_regex_prose_fixture_passes(tmp_path, monkeypatch, conn):
    """Real AGENTS.md prose: mid-sentence Doctor mentions emit zero findings."""
    rel = "AGENTS.md"
    body = (
        "## Hooks\n\n"
        "runtime/harness/claude/settings.json hooks call "
        "python3 -m yoke_core.engines.doctor; emergency status repair "
        "uses yoke lifecycle repair-status.\n"
    )
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 0})

    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_anchored_regex_positive_fixture_emits_two_findings(
    tmp_path, monkeypatch, conn
):
    """`$ ...doctor` AND `> ...doctor` on separate lines emits two findings."""
    rel = ".yoke/docs/commands.md"
    body = (
        "Examples:\n\n"
        "$ python3 -m yoke_core.engines.doctor\n"
        "> python3 -m yoke_core.engines.doctor\n"
    )
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 2})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    finding_lines = [ln for ln in _detail(rec).splitlines() if ln.startswith("- ")]
    assert len(finding_lines) == 2


# --- Check C: stale subcommand help disambiguation -------------------------
_PARENT_HELP = (
    "Available subcommands:\n  real-cmd    Do the real thing\n"
    "  other-cmd    Another thing\n"
)


def test_check_c_confabulated_subcommand_emits_check_a_finding(
    tmp_path, monkeypatch, conn
):
    """Subcommand --help fails AND sub NOT listed in parent --help: Check A."""
    rel = ".yoke/docs/commands.md"
    body = "    python3 -m runtime.api.foo nonexistent-cmd --bar baz\n"
    _setup(
        tmp_path,
        monkeypatch,
        {rel: body},
        {rel: 2},
        {
            ("runtime.api.foo", "nonexistent-cmd"): (1, "no such subcommand"),
            ("runtime.api.foo", None): (0, _PARENT_HELP),
        },
    )
    rec = _run(conn)
    detail = _detail(rec)
    assert rec.results[0].result == "WARN"
    assert "confabulated subcommand" in detail
    assert "nonexistent-cmd" in detail


def test_check_c_listed_but_broken_help_emits_stale_help_finding(
    tmp_path, monkeypatch, conn
):
    """Subcommand --help fails AND sub IS listed in parent --help: Check C."""
    rel = ".yoke/docs/commands.md"
    body = "    python3 -m runtime.api.foo real-cmd --bar baz\n"
    _setup(
        tmp_path,
        monkeypatch,
        {rel: body},
        {rel: 2},
        {
            ("runtime.api.foo", "real-cmd"): (1, "argparse error"),
            ("runtime.api.foo", None): (0, _PARENT_HELP),
        },
    )
    rec = _run(conn)
    detail = _detail(rec)
    assert rec.results[0].result == "WARN"
    assert "stale subcommand help" in detail
    assert "real-cmd" in detail


# --- Surface pass-through negatives ----------------------------------------
def test_gh_cli_surface_passes(tmp_path, monkeypatch, conn):
    """`gh issue list` is not a `python3 -m` invocation — Stage 1 filters it."""
    rel = ".yoke/docs/commands.md"
    body = "Run `gh issue list --state open` to see open issues.\n"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 2})
    assert _run(conn).results[0].result == "PASS"


def test_db_router_read_only_path_passes(tmp_path, monkeypatch, conn):
    """`db_router items get` matches the read-only-paths surface — passes."""
    from yoke_core.domain.function_inventory_data import RETAINED_TERMINAL_BOUNDARIES

    # Defense-in-depth: regression check for the parent work item's hard rule.
    assert any(
        "python3 -m yoke_core.cli.db_router" in b.surface
        for b in RETAINED_TERMINAL_BOUNDARIES
    )
    rel = ".agents/skills/yoke/refine/SKILL.md"
    body = "    python3 -m yoke_core.cli.db_router items get YOK-N spec\n"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 5})
    assert _run(conn).results[0].result == "PASS"


@pytest.mark.parametrize(
    "body",
    [
        "python3 -m yoke_core.tools.watch_doctor -- --full --fix\n",
        "python3 -m yoke_core.tools.watch_merge done-transition YOK-N\n",
        "python3 -m yoke_core.domain.worktree create YOK-N /repo\n",
        "python3 -m yoke_core.tools.executors ephemeral-verify p r b w d sha\n",
    ],
)
def test_permanent_tool_shaped_operation_passes(
    tmp_path,
    monkeypatch,
    conn,
    body,
):
    """Inventory-classified tools own their forwarded argument grammar."""
    rel = ".agents/skills/yoke/conduct/SKILL.md"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 5})
    assert _run(conn).results[0].result == "PASS"


@pytest.mark.parametrize(
    "body",
    [
        "python3 -m yoke_core.tools.watch_doctorish --bogus\n",
        (
            "python3 -m yoke_core.api.service_client "
            "coordination-lease-acquirex --bogus\n"
        ),
    ],
)
def test_permanent_surface_prefix_does_not_exempt_longer_token(
    tmp_path,
    monkeypatch,
    conn,
    body,
):
    """A permanent command's textual prefix cannot exempt a different token."""

    rel = ".agents/skills/yoke/conduct/SKILL.md"
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 5})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "confabulated" in _detail(rec) or "exits non-zero" in _detail(rec)


def test_operator_break_glass_surface_is_not_tool_shaped_exemption(
    tmp_path,
    monkeypatch,
    conn,
):
    """Permanent operator/debug commands remain subject to their own help."""

    rel = ".agents/skills/yoke/conduct/SKILL.md"
    body = (
        "python3 -m yoke_core.api.service_client coordination-lease-acquire --bogus\n"
    )
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 5})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "confabulated subcommand" in _detail(rec)


# --- Edges: archive, empty, truncation, repo-root self-skip ----------------
def test_archive_path_does_not_fire(tmp_path, monkeypatch, conn):
    """Files under docs/archive/ are exempt regardless of content.

    iter_tier_paths yields nothing — archive paths are not yielded by
    the real iterator for tiers 0/2/4/5 either.
    """
    rel = "docs/archive/cli-shape-history.md"
    _setup(tmp_path, monkeypatch, {rel: "$ python3 -m yoke_core.engines.doctor\n"}, {})
    assert _run(conn).results[0].result == "PASS"


def test_empty_file_emits_pass(tmp_path, monkeypatch, conn):
    rel = "docs/OVERVIEW.md"
    _setup(tmp_path, monkeypatch, {rel: ""}, {rel: 2})
    assert _run(conn).results[0].result == "PASS"


def test_self_skip_when_repo_root_unresolvable(monkeypatch, conn):
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()


def test_findings_truncated_to_budget(tmp_path, monkeypatch, conn):
    """100+ bare-Doctor lines in one file truncate to <=40 + summary."""
    rel = "runtime/agents/engineer.md"
    body = "# Heavy\n" + ("$ python3 -m yoke_core.engines.doctor\n" * 100)
    _setup(tmp_path, monkeypatch, {rel: body}, {rel: 4})
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "more references" in detail
    finding_lines = [ln for ln in detail.splitlines() if ln.startswith("- ")]
    assert len(finding_lines) == 40
