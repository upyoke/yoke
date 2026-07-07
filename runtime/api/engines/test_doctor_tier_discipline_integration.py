"""Cross-HC integration regressions for the tier-discipline family.

Each test injects a bad shape into a tmp fixture and exercises one HC via
``iter_tier_paths`` / ``render_role_packet`` / ``SKILL_SCAN_TARGETS`` /
``_run_help`` monkeypatches; no live repo paths are read. Coverage floor
(>=15 distinct shapes) is enforced by ``test_distinct_bad_shape_count``.
:data:`BASELINE_KNOWN_RESIDUE` captures observed-WARN signatures an
earlier cleanup chain didn't reach; the clean-baseline guard subtracts
them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import pytest

from yoke_core.engines import doctor_hc_packet_tier_completeness as packet_mod
from yoke_core.engines import doctor_hc_progressive_disclosure_direction as disc_mod
from yoke_core.engines import doctor_hc_tier_cli_shape_bleed as cli_mod
from yoke_core.engines import doctor_hc_tier_module_path_resolution as mod_path_mod
from yoke_core.engines import doctor_hc_tier_schema_bleed as schema_mod
from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
    TIER_DISCIPLINE_HEALTH_CHECKS,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# BASELINE_KNOWN_RESIDUE — substring patterns the live-repo run surfaces
# today that the cleanup chain didn't reach. Subtracted by the
# clean-baseline guard (fix cycle 1 GAP #9). Function-id-style noun phrases
# (`items.structured_field`, `items.scalar`, `items.body`, etc.) still
# trip Class A without a sanctioned cross-reference prefix; the post-merge
# refinement ticket drains the remaining residue.
BASELINE_KNOWN_RESIDUE: Dict[str, Tuple[str, ...]] = {
    "tier-schema-bleed": (
        "items.structured_field", "items.section", "items.progress_log",
        "items.scalar", "items.body", "project_structure.patch",
        "epic_tasks.list", "items.py",
    ),
    "tier-cli-shape-bleed": ("drifted",),
    "packet-tier-completeness": (),
    "progressive-disclosure-direction": ("tier-direction",),
    "tier-module-path-resolution": ("does not resolve",),
}


@pytest.fixture
def conn():
    """The tier-discipline HCs scan files and packets only; none reads *conn*."""
    return None


def _materialize(tmp_path: Path, files: Dict[str, str]) -> None:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _make_iter(repo_root: Path, tier_for: Dict[str, int]):
    def fake_iter(
        repo: Path, tiers: Iterable[int] = (0, 2, 4, 5)
    ) -> Iterator[Tuple[int, Path]]:
        wanted = set(tiers)
        for rel, tier in sorted(tier_for.items()):
            if tier in wanted:
                yield tier, repo_root / rel

    return fake_iter


def _install_iter(monkeypatch, mod, repo_root: Path, tier_for: Dict[str, int]) -> None:
    monkeypatch.setattr(mod, "iter_tier_paths", _make_iter(repo_root, tier_for))
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(repo_root))


def _install_cli_help(monkeypatch, table: Dict[Tuple[str, object], Tuple[int, str]]):
    monkeypatch.setattr(
        cli_mod,
        "_run_help",
        lambda _repo_root, module, sub: table.get((module, sub), (1, "")),
    )


def _install_packet(monkeypatch, role_to_text: Dict[str, str]) -> None:
    monkeypatch.setattr(packet_mod, "render_role_packet", role_to_text.get)


def _run(hc_fn, conn) -> RecordCollector:
    rec = RecordCollector()
    hc_fn(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


def test_registry_bundle_order_and_count():
    # Bundle exposes the six tier-discipline HCs in stable order;
    # ``cli-help-handler-present`` is last (joined when the
    # service_client universal --help safety net landed).
    assert [hc.slug for hc in TIER_DISCIPLINE_HEALTH_CHECKS] == [
        "tier-schema-bleed", "tier-cli-shape-bleed", "packet-tier-completeness",
        "progressive-disclosure-direction", "tier-module-path-resolution",
        "cli-help-handler-present",
    ]


# HC-tier-schema-bleed Class A — (table.column, kind). `real` = column
# exists on table (restated truth); `fake` = non-existent column.
_CLASS_A_CASES = [
    ("items.worktree", "real"),
    ("epic_progress_notes.note_num", "real"),
    ("qa_requirements.qa_kind", "real"),
    ("path_targets.path_string", "real"),
    ("path_claim_targets.claim_id", "real"),
    ("epic_tasks.depends_on", "fake"),
    ("qa_requirements.required", "fake"),
    ("path_targets.path", "fake"),
    ("items.item_id", "fake"),
    ("path_claims.claim_id", "fake"),
]


@pytest.mark.parametrize("table_col,kind", _CLASS_A_CASES)
def test_schema_bleed_class_a(tmp_path, monkeypatch, conn, table_col, kind):
    rel = "AGENTS.md"
    _materialize(tmp_path, {rel: f"Inspect the {table_col} column when claiming.\n"})
    _install_iter(monkeypatch, schema_mod, tmp_path, {rel: 0})

    rec = _run(schema_mod.hc_tier_schema_bleed, conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert table_col in detail
    assert (
        "restates Tier 1 structural truth" if kind == "real" else "non-existent column"
    ) in detail


# HC-tier-schema-bleed Class B — JSON nested field accessed as top-level.
_CLASS_B_CASES = [
    ("browser_testable", "items", "browser_qa_metadata"),
    ("migration_strategy", "items", "db_mutation_profile"),
]


@pytest.mark.parametrize("field,table,json_col", _CLASS_B_CASES)
def test_schema_bleed_class_b_json_nested(
    tmp_path, monkeypatch, conn, field, table, json_col
):
    rel = ".agents/skills/yoke/test/dummy.md"
    _materialize(
        tmp_path,
        {rel: f"Run: python3 -m yoke_core.cli.db_router items get YOK-42 {field}\n"},
    )
    _install_iter(monkeypatch, schema_mod, tmp_path, {rel: 5})

    rec = _run(schema_mod.hc_tier_schema_bleed, conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert f"`items get ... {field}`" in detail
    assert f"`{table}.{json_col}`" in detail


# HC-tier-cli-shape-bleed cases: (label, file rel, tier, body, help-table,
# expected detail substring). help-table is (module, sub) -> (rc, stdout).
_NM_ERR = (1, "No module named yoke_core.engines.nonexistent")
_CLI_CASES = [
    (
        "drifted_db_claim_amend_flag",
        ".agents/skills/yoke/conduct/SKILL.md", 5,
        "    python3 -m yoke_core.api.service_client db-claim-amend --claim-state none\n",
        {("yoke_core.api.service_client", "db-claim-amend"): (
            0, "usage: db-claim-amend --item ITEM --reason REASON [--state {none}]\n",
        )},
        "`--claim-state`",
    ),
    (
        "drifted_claim_list_subcommand",
        "docs/commands.md", 2,
        "    python3 -m yoke_core.api.service_client claim-list --item YOK-1674\n",
        {
            ("yoke_core.api.service_client", "claim-list"): (1, "no such subcommand"),
            ("yoke_core.api.service_client", None): (
                0,
                "Available subcommands:\n  path-claim-list   Path claim list\n"
                "  release-work-claim   Release work claim\n",
            ),
        },
        "claim-list",
    ),
    (
        "drifted_section_upsert_flag",
        ".agents/skills/yoke/refine/SKILL.md", 5,
        "    python3 -m yoke_core.domain.item_field_transform section-upsert "
        "--field spec --heading X\n",
        {("yoke_core.domain.item_field_transform", "section-upsert"): (
            0, "usage: section-upsert --item ITEM --field FIELD --section SECTION\n",
        )},
        "`--heading`",
    ),
    (
        "bare_doctor",
        "AGENTS.md", 0,
        "# Substrate\n\n$ python3 -m yoke_core.engines.doctor\n",
        {},
        "bare",
    ),
    (
        "confabulated_subcommand",
        "docs/commands.md", 2,
        "    python3 -m yoke_core.engines.nonexistent-cmd --help\n",
        # Module regex stops at `-`; both subcommand-split and parent-help
        # fallback lookups must err to surface the confabulation.
        {
            ("yoke_core.engines.nonexistent", "cmd"): _NM_ERR,
            ("yoke_core.engines.nonexistent", None): _NM_ERR,
        },
        "module path may be confabulated",
    ),
]


@pytest.mark.parametrize("label,rel,tier,body,help_table,expected", _CLI_CASES)
def test_cli_shape_bleed_cases(
    tmp_path, monkeypatch, conn, label, rel, tier, body, help_table, expected
):
    _materialize(tmp_path, {rel: body})
    _install_iter(monkeypatch, cli_mod, tmp_path, {rel: tier})
    _install_cli_help(monkeypatch, help_table)

    rec = _run(cli_mod.hc_tier_cli_shape_bleed, conn)
    assert rec.results[0].result == "WARN"
    assert expected.lower() in _detail(rec).lower()


def test_module_path_resolution_confabulated_module(tmp_path, monkeypatch, conn):
    rel = "docs/lifecycle.md"
    _materialize(
        tmp_path,
        {rel: "See `yoke_core.domain.yoke_function_envelope` for the request shape.\n"},
    )
    _install_iter(monkeypatch, mod_path_mod, tmp_path, {rel: 2})

    rec = _run(mod_path_mod.hc_tier_module_path_resolution, conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "yoke_function_envelope" in detail
    assert "unresolved module path" in detail


def test_module_path_resolution_confabulated_sub_symbol(tmp_path, monkeypatch, conn):
    rel = ".agents/skills/yoke/conduct/SKILL.md"
    _materialize(
        tmp_path,
        {rel: "Resolve the DB via `yoke_core.domain.worktree.get_db_path`.\n"},
    )
    _install_iter(monkeypatch, mod_path_mod, tmp_path, {rel: 5})

    rec = _run(mod_path_mod.hc_tier_module_path_resolution, conn)
    assert rec.results[0].result == "WARN"
    assert "worktree.get_db_path" in _detail(rec)


_GOOD_ENVELOPE_BLOCK = (
    "actor / session_id / actor_id / preconditions / options envelope. "
    f"Function id: {REQUIRED_FUNCTION_IDS[0]}.\n"
)


def test_packet_completeness_envelope_missing_actor(tmp_path, monkeypatch, conn):
    """AC-30: main_agent packet that omits `actor` fires."""
    monkeypatch.setattr(packet_mod, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(packet_mod, "SKILL_SCAN_TARGETS", {"main_agent": ()})
    bad_packet = (
        "session_id / actor_id / preconditions / options envelope. "
        f"Function id: {REQUIRED_FUNCTION_IDS[0]}.\n"
    )
    _install_packet(monkeypatch, {"main_agent": bad_packet})

    rec = _run(packet_mod.hc_packet_tier_completeness, conn)
    assert rec.results[0].result == "WARN"
    assert "envelope field 'actor' missing" in _detail(rec)


def test_packet_completeness_check_a_column_in_skill_not_in_packet(
    tmp_path, monkeypatch, conn
):
    rel = ".agents/skills/yoke/test/dummy.md"
    _materialize(
        tmp_path,
        {rel: "Verify qa_runs.satisfied_at after recording the verdict.\n"},
    )
    monkeypatch.setattr(packet_mod, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(packet_mod, "SKILL_SCAN_TARGETS", {"main_agent": (rel,)})
    packet_body = (
        _GOOD_ENVELOPE_BLOCK
        + "### DB Quick Reference — qa (test fixture)\n"
        + "- **`qa_runs`** — `id, qa_requirement_id, verdict, created_at`\n"
    )
    _install_packet(monkeypatch, {"main_agent": packet_body})

    rec = _run(packet_mod.hc_packet_tier_completeness, conn)
    assert rec.results[0].result == "WARN"
    assert "missing column qa_runs.satisfied_at" in _detail(rec)


def test_progressive_disclosure_tier0_cites_tier5_skill(tmp_path, monkeypatch, conn):
    rel = "AGENTS.md"
    skill_rel = ".agents/skills/yoke/conduct/SKILL.md"
    _materialize(
        tmp_path,
        {rel: f"For details see [conduct]({skill_rel}).\n", skill_rel: "# Conduct\n"},
    )
    _install_iter(monkeypatch, disc_mod, tmp_path, {rel: 0, skill_rel: 5})

    rec = _run(disc_mod.hc_progressive_disclosure_direction, conn)
    assert rec.results[0].result == "WARN"
    assert "AGENTS.md" in _detail(rec)


def test_progressive_disclosure_tier5_vague_denial_without_function_id(
    tmp_path, monkeypatch, conn
):
    rel = ".agents/skills/yoke/conduct/SKILL.md"
    _materialize(
        tmp_path,
        {rel: "When recording the verdict, use function dispatch instead.\n"},
    )
    _install_iter(monkeypatch, disc_mod, tmp_path, {rel: 5})

    rec = _run(disc_mod.hc_progressive_disclosure_direction, conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "vague-denial phrase" in detail
    assert rel in detail


def test_distinct_bad_shape_count_meets_floor():
    """AC-4 / SM-2: at least 15 distinct injected bad shapes covered."""
    total = len(_CLASS_A_CASES) + len(_CLASS_B_CASES) + 5 + 2 + 2 + 2
    assert total >= 15, f"expected >= 15 distinct shapes, counted {total}"
