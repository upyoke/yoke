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
    compact = " ".join(text.split())
    assert "yoke project-structure deploy-defaults get" in text
    assert "yoke workflows mechanics get --json" in text
    assert "yoke deployment-flows get" in text
    assert "yoke deployment-flows list --project" in text
    assert "target_tier" in text
    assert "target_environment" in text
    assert "yoke workflows definition get" not in text
    assert "|| true" not in text
    assert "--field" not in text
    assert "is not route authority" in compact
    assert "inherits" in compact
    assert "not a merge-only exemption" in compact
    assert "NEVER store `none`" in compact
    assert "omit `--deployment-flow`" in text
    assert "Task stays exempt" in text
    assert "delivery-requirements.md" in text
    assert "do not rewrite shared defaults" in text
    assert "explicit merge-only" in compact


def test_docs_state_persistent_default_is_not_automatic() -> None:
    text = DOCS.read_text(encoding="utf-8")
    compact = " ".join(text.split())
    assert "when present, use its flow automatically" not in text
    assert "Merge-only or `-internal` defaults attach" not in text
    assert "Never classify by an id suffix" in compact
    assert "inherits the project/workflow default" in compact
    assert "not waive delivery" in compact
    assert "persistent default" in text
    assert "Never store the literal `none`" in text
    assert "yoke workflows delivery-default set" in text
    assert "Task stays exempt" in text
    assert "execution_supported=false" in text
    assert "qa.requirement.add" in text


def test_intake_persists_delivery_evidence_as_existing_qa_rows() -> None:
    text = (REPO / ".agents/skills/yoke/idea/delivery-requirements.md").read_text(
        encoding="utf-8"
    )
    compact = " ".join(text.split())
    assert "qa.requirement.add" in text
    assert "--qa-phase post_deploy" in text
    assert "--target-env" in text
    assert "browser-inspection" in text
    assert "does **not** add approval" in text
    assert "yoke items scalar update" in text
    assert "yoke deployment-flows validate" in text
    assert "execution_supported=false" in text
    assert "yoke workflows item-posture amend" in text
    assert "actors" in text
    assert "mode=all" in text
    assert "do not wait for an environment" in text
    assert "does not re-run or waive the original" in compact
    assert "prior candidate's pass does not satisfy" in compact
    assert "never admitted this source" in compact
    assert "item-scoped QA stage" in text
    assert "Never `update-stages`" in text


def test_explicit_approval_requires_this_operator_not_human_if_unsure() -> None:
    text = (REPO / ".agents/skills/yoke/idea/delivery-requirements.md").read_text(
        encoding="utf-8"
    )
    compact = " ".join(text.split())
    assert '"Have me approve it"' in compact
    assert "required_human" in compact
    assert "`required_human` or `human_if_unsure`" not in compact
    assert "`human_if_unsure` can pass without asking" in compact
    assert "explicitly conditional" in compact
    assert "compatible reviewer requirement" in compact
    assert "Do not replace a matching policy" in compact
    assert "item-scoped QA stage" in compact
    assert "persistent_environment" in compact
    assert "Never `update-stages`" in compact


def test_dash_routes_intake_screenshot_to_delivery_requirements() -> None:
    text = (REPO / ".agents/skills/yoke/dash/SKILL.md").read_text(encoding="utf-8")
    assert "--verification-method browser-inspection" in text
    assert "delivery-requirements.md" in text
