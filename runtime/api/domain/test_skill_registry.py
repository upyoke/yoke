"""Skill inventory covers installed procedures and all dispatch surfaces."""

from pathlib import Path

import pytest

from yoke_contracts.session_queue_posture import SESSION_MODES
from yoke_contracts.skill_registry import SKILLS, STAGE_SKILL_IDS
from yoke_core.domain.frontier_types import AdapterCategory
from yoke_core.domain.harness_capability_registry import (
    HARNESS_UNIVERSE,
    compact_entrypoint_display,
    downstream_paths_for_manifest,
    prompt_reminder_lines,
    safe_operator_surface,
)
from yoke_core.domain.scheduler_routing import _compute_next_step
from yoke_core.domain.scheduler_types import NextStep
from yoke_core.domain.session_launch_mandate import item_entrypoint
from yoke_core.domain.yaml_helper import parse_document
from yoke_core.tools import render_skill_registry_inline
from yoke_core.tools.render_field_note_inline import INVENTORY

ROOT = Path(__file__).resolve().parents[3]


def test_registry_covers_each_installed_skill_exactly_once():
    paths = {skill.body_path for skill in SKILLS}
    installed = {
        str(path.relative_to(ROOT))
        for path in (ROOT / ".agents/skills/yoke").rglob("SKILL.md")
        if path.parent != ROOT / ".agents/skills/yoke"
    }
    assert paths == installed
    assert len(paths) == len(SKILLS) == len({skill.id for skill in SKILLS})
    assert paths <= set(INVENTORY)
    assert all(
        "<!-- BEGIN GENERATED: field-note-directive -->" in (ROOT / path).read_text()
        for path in paths
    )
    assert {skill.session_mode for skill in SKILLS} <= SESSION_MODES


def test_stage_skills_route_and_launch_on_every_harness():
    assert {step.value for step in NextStep} - {"wait"} == STAGE_SKILL_IDS
    public_ref = "PROJECT-" + str(1)
    for skill in SKILLS:
        command = item_entrypoint(skill.id, public_ref)
        if skill.kind == "stage":
            assert command == f"{skill.entrypoint} {public_ref}"
            assert (
                _compute_next_step(AdapterCategory(skill.id)).next_step.value
                == skill.id
            )
            assert skill.id in downstream_paths_for_manifest({})
        else:
            assert command is None
    assert item_entrypoint("unknown", "PROJECT-" + str(1)) is None
    assert _compute_next_step(AdapterCategory.SKIP).next_step is NextStep.WAIT
    assert all(
        command.harness_support == HARNESS_UNIVERSE
        for command in safe_operator_surface()
    )


def test_generated_skill_teaching_is_current():
    result = render_skill_registry_inline.render(ROOT, check=True)
    assert result.ok
    assert not result.changed
    assert not result.missing_markers
    assert not result.missing_files


def test_manifest_limitations_filter_derived_stage_skills():
    skill_id = next(iter(STAGE_SKILL_IDS))
    manifest = {"supports": {"disabled_downstream_paths": [skill_id]}}
    assert set(downstream_paths_for_manifest(manifest)) == STAGE_SKILL_IDS - {skill_id}


def test_argument_hints_have_one_authoring_source():
    for skill in SKILLS:
        header = (ROOT / skill.body_path).read_text().split("---", 2)[1]
        assert parse_document(header)["argument-hint"] == skill.arguments
        assert render_skill_registry_inline.ARGUMENT_HINT_NOTICE in header
    by_id = {skill.id: skill for skill in SKILLS}
    assert '"instruction"' in by_id["dash"].display
    assert "--no-new-items" in by_id["feed"].display


@pytest.mark.parametrize(
    "frontmatter",
    [
        '---\nname: dash\nargument-hint: "stale"\n---\nbody\n',
        "---\nname: dash\n---\nbody\n",
        "name: dash\nbody\n",
    ],
)
def test_hint_check_detects_drift_without_writing(tmp_path, monkeypatch, frontmatter):
    skill = next(skill for skill in SKILLS if skill.id == "dash")
    monkeypatch.setattr(render_skill_registry_inline, "SKILLS", (skill,))
    target = tmp_path / skill.body_path
    target.parent.mkdir(parents=True)
    target.write_text(frontmatter)
    result = render_skill_registry_inline._render_argument_hints(tmp_path, check=True)
    assert result.changed or not result.ok
    assert target.read_text() == frontmatter


def test_internal_inventory_lists_only_internal_skill_bodies():
    content = render_skill_registry_inline.internal_content_for_path("")
    for skill in SKILLS:
        assert (f"`{skill.body_path}`" in content) == (skill.kind == "internal")
    assert "implement/implementing/SKILL.md" in content


def test_startup_orientation_retains_compact_order_and_manifest_filters():
    startup = sorted(
        (s for s in SKILLS if s.startup_order is not None),
        key=lambda s: s.startup_order,
    )
    assert [s.id for s in startup] == ["idea", "refine", "implement", "polish", "usher"]
    assert compact_entrypoint_display() == ", ".join(s.display for s in startup)
    assert prompt_reminder_lines() == [
        f"  {s.display} -- {s.description}" for s in startup
    ]
    assert compact_entrypoint_display([]) == ""
    assert prompt_reminder_lines([]) == []
