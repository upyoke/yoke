"""Intake assignment: persistent defaults are not applied blindly."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INFER = REPO / ".agents/skills/yoke/idea/infer-and-create.md"
SIBLING = REPO / ".agents/skills/yoke/idea/infer-deployment-flow.md"
DOCS = REPO / "docs/public/reference/db-reference/projects-and-flows.md"


def test_idea_defers_flow_assignment_to_sibling() -> None:
    text = INFER.read_text(encoding="utf-8")
    assert "infer-deployment-flow.md" in text
    assert "without further inference" not in text


def test_sibling_omits_persistent_default_for_non_delivery() -> None:
    text = SIBLING.read_text(encoding="utf-8")
    assert "yoke project-structure deploy-defaults get" in text
    assert "yoke deployment-flows get" in text
    assert "target_tier" in text
    assert "target_environment" in text
    assert "-internal" in text
    assert "non-delivery" in text
    assert "NEVER store `none`" in text
    assert "omit `--deployment-flow`" in text


def test_docs_state_persistent_default_is_not_automatic() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "when present, use its flow automatically" not in text
    assert "Merge-only or `-internal` defaults attach" in text
    assert "persistent default" in text
    assert "Never store the literal `none`" in text
