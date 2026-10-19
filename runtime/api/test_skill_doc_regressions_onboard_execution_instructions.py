"""Onboard's guidance review moves work-scoped rules into execution instructions."""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

from yoke_cli.commands.adapters import workflow_execution_instructions as adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_STEP = (
    REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard" / "strategy-conversation.md"
)
PUBLIC_ONBOARD = REPO_ROOT / "docs" / "public" / "projects" / "index.md"

_CONFIGURATORS = {
    "create": adapter._content_args,
    "set-scope": adapter._set_scope_args,
    "resolve": adapter._resolve_args,
}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SAMPLE = {"instruction_id": "7", "project_id": "1"}


def _guidance_section() -> str:
    text = STRATEGY_STEP.read_text(encoding="utf-8")
    start = text.index("## Review existing guidance")
    return text[start : text.index("\n## ", start + 1)]


def _recipe_lines(section: str) -> list[str]:
    return [
        line
        for line in section.splitlines()
        if line.startswith("yoke workflow execution-instruction ")
    ]


def test_guidance_review_sorts_every_turn_rules_from_work_scoped_rules():
    section = _guidance_section()
    assert "outside the Yoke managed block" in section
    assert "**Every turn** (holds in all work): leave it where it is." in section
    assert (
        "propose it as an\n  execution instruction, naming its scope and delivery point"
        in section
    )
    assert "one rule at a time" in section
    assert "For each approved rule\nonly" in section
    assert "delete the moved text from its source file" in section


def test_guidance_review_sits_before_the_decision_walk():
    text = STRATEGY_STEP.read_text(encoding="utf-8")
    review = text.index("## Review existing guidance")
    assert text.index("## Ground drafts in the repository") < review
    assert review < text.index("## Draft, then decide one thing at a time")
    assert "a rule moves only through an approved guidance proposal" in text


def test_guidance_recipe_creates_scopes_then_resolves_with_live_flags():
    lines = _recipe_lines(_guidance_section())
    assert [shlex.split(line)[3] for line in lines] == [
        "create",
        "set-scope",
        "resolve",
    ]
    for line in lines:
        words = shlex.split(_PLACEHOLDER.sub(lambda m: _SAMPLE.get(m[1], m[1]), line))
        parser = argparse.ArgumentParser(exit_on_error=False)
        _CONFIGURATORS[words[3]](parser)
        parser.add_argument("--json", action="store_true")
        parser.parse_args(words[4:])


def test_set_scope_binds_this_project_and_names_the_unscoped_default():
    section = _guidance_section()
    set_scope = _recipe_lines(section)[1]
    assert "--workflow {workflow}" in set_scope
    assert "--project-id {project_id}" in set_scope
    assert "reaches no work, until `set-scope`" in section
    assert "../../../../.yoke/docs/projects/execution-instructions.md" in section


def test_public_onboarding_page_names_the_guidance_review():
    text = PUBLIC_ONBOARD.read_text(encoding="utf-8")
    assert "reviews the project's own rules" in text
    assert (
        "only\napproved ones are created; every-turn rules stay where they are" in text
    )
