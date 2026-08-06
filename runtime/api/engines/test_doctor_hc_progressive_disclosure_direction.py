"""Unit tests for HC-progressive-disclosure-direction."""

from __future__ import annotations

import pytest

from yoke_project_checks import check_progressive_disclosure_direction as mod
from yoke_project_checks.check_progressive_disclosure_direction import HC_SLUG
from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
)
from .doctor_hc_progressive_disclosure_test_support import (
    _ARCHITECT_AGENT,
    _CONDUCT_SKILL,
    _detail,
    _ENGINEER_AGENT,
    _FN_INVENTORY,
    _materialize,
    _run,
    _setup,
    conn as conn,
)


def test_check_a_positive_tier_0_cites_tier_5_skill(tmp_path, monkeypatch, conn):
    """Tier 0 file citing a Tier 5 SKILL.md fires backward-reference."""

    _setup(
        tmp_path,
        monkeypatch,
        {
            "AGENTS.md": f"See the [conduct skill]({_CONDUCT_SKILL}).\n",
            _CONDUCT_SKILL: "# conduct\n",
        },
        {"AGENTS.md": 0, _CONDUCT_SKILL: 5},
    )
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert rec.results[0].check_id == HC_SLUG
    detail = _detail(rec)
    assert "tier 0 file references backward tier 5" in detail
    assert "conduct/SKILL.md" in detail


@pytest.mark.parametrize(
    "files, tier_for",
    [
        # Tier 0 -> Tier 3 forward
        (
            {
                "AGENTS.md": f"See [inv]({_FN_INVENTORY}).\n",
                _FN_INVENTORY: "# inventory\n",
            },
            {"AGENTS.md": 0, _FN_INVENTORY: 3},
        ),
        # Tier 5 -> Tier 4 allowed
        (
            {
                _CONDUCT_SKILL: f"Dispatch [engineer]({_ENGINEER_AGENT}).\n",
                _ENGINEER_AGENT: "# engineer\n",
            },
            {_CONDUCT_SKILL: 5, _ENGINEER_AGENT: 4},
        ),
        # Tier 4 -> Tier 4 same-tier
        (
            {
                _ENGINEER_AGENT: f"With [arch]({_ARCHITECT_AGENT}).\n",
                _ARCHITECT_AGENT: "# architect\n",
            },
            {_ENGINEER_AGENT: 4, _ARCHITECT_AGENT: 4},
        ),
        # .py source citation exempt
        (
            {"AGENTS.md": "See runtime/api/engines/doctor.py.\n"},
            {"AGENTS.md": 0},
        ),
    ],
    ids=["tier-0-to-3", "tier-5-to-4", "tier-4-same", "py-exempt"],
)
def test_check_a_negative_allowed_citations(
    tmp_path, monkeypatch, conn, files, tier_for
):
    """Forward / same-tier / .py citations all PASS Check A."""

    _setup(tmp_path, monkeypatch, files, tier_for)
    detail = _detail(_run(conn))
    assert "backward tier" not in detail
    assert "is not classified" not in detail


def test_check_b_positive_vague_denial_without_function_id(tmp_path, monkeypatch, conn):
    """Vague-denial phrase without a registered function id fires."""

    _setup(
        tmp_path,
        monkeypatch,
        {_CONDUCT_SKILL: "When mutating, use function dispatch.\n"},
        {_CONDUCT_SKILL: 5},
    )
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "vague-denial phrase used without a concrete registered" in _detail(rec)


@pytest.mark.parametrize(
    "body",
    [
        f"Use function dispatch (e.g., {REQUIRED_FUNCTION_IDS[0]}).\n",
        "Use function dispatch — no registered function id exists yet.\n",
    ],
    ids=["names-function-id", "explicit-absence-note"],
)
def test_check_b_negative_vague_denial_exemptions(tmp_path, monkeypatch, conn, body):
    """Line names a concrete id OR carries the absence note — PASSES."""

    _setup(tmp_path, monkeypatch, {_CONDUCT_SKILL: body}, {_CONDUCT_SKILL: 5})
    assert "vague-denial" not in _detail(_run(conn))


def test_archive_path_does_not_fire(tmp_path, monkeypatch, conn):
    """``docs/archive/`` content is exempt by default (NFR-5)."""

    rel = "docs/archive/decisions/legacy.md"
    body = f"use function dispatch.\nSee [conduct]({_CONDUCT_SKILL}).\n"
    _materialize(tmp_path, {rel: body, _CONDUCT_SKILL: "# conduct\n"})
    monkeypatch.setattr(
        mod, "iter_tier_paths", lambda repo, tiers=(0, 2, 4, 5): iter([(6, repo / rel)])
    )
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(tmp_path))

    assert _run(conn).results[0].result == "PASS"


def test_unclassified_path_one_warn_per_unique(tmp_path, monkeypatch, conn):
    """Two citations of the same unclassified path emit one WARN."""

    unknown = "docs/unknown/area.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _ENGINEER_AGENT: f"See [unknown]({unknown}) for context.\n",
            _ARCHITECT_AGENT: f"Also referenced: [unknown]({unknown}).\n",
        },
        {_ENGINEER_AGENT: 4, _ARCHITECT_AGENT: 4},
    )
    rec = _run(conn)
    detail = _detail(rec)
    assert detail.count("is not classified") == 1
    assert unknown in detail


def test_relative_sibling_skill_reference_is_classified(
    tmp_path,
    monkeypatch,
    conn,
):
    """Skill-local references resolve relative to the citing skill file."""
    sibling = ".agents/skills/yoke/conduct/dispatch-context.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _CONDUCT_SKILL: "Continue with [dispatch context](dispatch-context.md).\n",
            sibling: "# Dispatch context\n",
        },
        {_CONDUCT_SKILL: 5, sibling: 5},
    )

    assert _run(conn).results[0].result == "PASS"


def test_explicit_skill_root_shorthand_reference_is_classified(
    tmp_path,
    monkeypatch,
    conn,
):
    """A command/path shorthand resolves from the canonical Yoke skill root."""
    target = ".agents/skills/yoke/idea/body-and-sync.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _CONDUCT_SKILL: "Compare [idea intake](idea/body-and-sync.md).\n",
            target: "# Body and sync\n",
        },
        {_CONDUCT_SKILL: 5, target: 5},
    )

    assert _run(conn).results[0].result == "PASS"


def test_arbitrary_suffix_stripping_does_not_classify_invented_prefix(
    tmp_path,
    monkeypatch,
    conn,
):
    """An invented path cannot resolve merely because its suffix is unique."""
    target = ".agents/skills/yoke/conduct/SKILL.md"
    invented = "invented/prefix/conduct/SKILL.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _ENGINEER_AGENT: f"See [invented]({invented}).\n",
            target: "# Conduct\n",
        },
        {_ENGINEER_AGENT: 4, target: 5},
    )

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "is not classified into a teaching tier" in _detail(rec)
    assert invented in _detail(rec)


def test_missing_bare_filename_is_reported_not_suppressed(
    tmp_path,
    monkeypatch,
    conn,
):
    """An unresolved basename remains visible to the classification check."""
    missing = "definitely-missing.md"
    _setup(
        tmp_path,
        monkeypatch,
        {_CONDUCT_SKILL: f"See [missing]({missing}).\n"},
        {_CONDUCT_SKILL: 5},
    )

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "is not classified into a teaching tier" in _detail(rec)
    assert missing in _detail(rec)


def test_generated_command_doc_resolves_scoped_phase_and_allows_link(
    tmp_path,
    monkeypatch,
    conn,
):
    """The command catalog resolves phase labels under its command heading."""
    commands = ".yoke/docs/reference/commands.md"
    target = ".agents/skills/yoke/shepherd/finalize.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            commands: "### shepherd\n\n**Phase files:** `finalize.md`.\n",
            target: "# Finalize\n",
        },
        {commands: 2, target: 5},
    )

    assert _run(conn).results[0].result == "PASS"


def test_dynamic_scratch_filename_is_not_a_teaching_citation(
    tmp_path,
    monkeypatch,
    conn,
):
    """A named per-dispatch scratch artifact is not a repository doc path."""
    body = "Read the generated `product-designer-spec.md` scratch artifact.\n"
    _setup(
        tmp_path,
        monkeypatch,
        {"runtime/agents/product-designer.md": body},
        {"runtime/agents/product-designer.md": 4},
    )

    assert _run(conn).results[0].result == "PASS"


def test_explicit_ouroboros_root_alias_is_classified(
    tmp_path,
    monkeypatch,
    conn,
):
    """The documented ``yoke/ouroboros`` alias maps only to that root."""
    target = "ouroboros/patterns.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _CONDUCT_SKILL: "See [patterns](yoke/ouroboros/patterns.md).\n",
            target: "# Patterns\n",
        },
        {_CONDUCT_SKILL: 5},
    )

    assert _run(conn).results[0].result == "PASS"


def test_existing_configuration_asset_is_not_a_teaching_tier(
    tmp_path,
    monkeypatch,
    conn,
):
    """Manifest/config references do not participate in teaching direction."""
    manifest = "runtime/harness/codex/manifest.json"
    _setup(
        tmp_path,
        monkeypatch,
        {
            "AGENTS.md": f"Read [{manifest}]({manifest}).\n",
            manifest: "{}\n",
        },
        {"AGENTS.md": 0},
    )

    assert _run(conn).results[0].result == "PASS"


def test_self_skips_when_repo_root_unresolvable(monkeypatch, conn):
    """Falsy ``_resolve_repo_root`` → PASS with "skip" detail."""

    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()
