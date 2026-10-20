"""Intake assignment: persistent defaults are not applied blindly."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INFER = REPO / ".agents/skills/yoke/idea/infer-and-create.md"
SIBLING = REPO / ".agents/skills/yoke/idea/infer-deployment-flow.md"
DOCS = REPO / "docs/public/databases/model/projects.md"


def test_idea_defers_flow_assignment_to_sibling() -> None:
    text = INFER.read_text(encoding="utf-8")
    assert "infer-deployment-flow.md" in text
    assert "without further inference" not in text


def test_sibling_omits_persistent_default_for_non_delivery() -> None:
    text = SIBLING.read_text(encoding="utf-8")
    compact = " ".join(text.split())
    assert "yoke project-structure deploy-defaults get" in text
    assert "yoke workflows mechanics get --json" in text
    assert "yoke workflows definition get" not in text
    assert "|| true" not in text
    assert "--field" not in text
    assert "judged by its fields, not its id" in compact
    assert "NEVER store `none`" in compact
    assert "omit `--deployment-flow`" in text
    assert "Task items omit it" in compact
    assert "delivery-requirements.md" in text


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


def _intake() -> str:
    text = (REPO / ".agents/skills/yoke/idea/delivery-requirements.md").read_text(
        encoding="utf-8"
    )
    return " ".join(text.split())


def test_intake_persists_delivery_evidence_as_existing_qa_rows() -> None:
    compact = _intake()
    assert "yoke qa requirement add" in compact
    assert "--method-id browser-inspection --qa-phase post_deploy" in compact
    assert "--target-env" in compact
    assert "yoke items scalar update PREFIX-N --field deployment_flow" in compact
    assert "yoke workflows item-posture amend" in compact
    assert "never bind `post_deploy` to review" in compact
    assert "Never edit a shared flow" in compact
    assert "Intake only persists: never run QA or create deployment runs." in compact


def test_explicit_approval_requires_this_operator_not_human_if_unsure() -> None:
    compact = _intake()
    assert "A screenshot does **not** add approval." in compact
    assert '"Have me approve it"' in compact
    assert "`required_human` on the item-scoped QA stage" in compact
    assert "operator in `actors`" in compact
    assert "`mode=all`" in compact
    assert "`human_if_unsure` only for explicitly conditional approval" in compact
    # The target kind is the flow's configured stage, not a fixed one: a
    # release-preview stage approves a run_preview target and names no
    # environment, so teaching only the persistent kind misconfigures it.
    assert "`persistent_environment`" in compact
    assert "`run_preview`" in compact
    assert "never assume one" in compact


def test_dash_routes_intake_screenshot_to_browser_inspection() -> None:
    dash = REPO / ".agents/skills/yoke/dash"
    claim = " ".join((dash / "file-and-claim.md").read_text(encoding="utf-8").split())
    verify = (dash / "verify.md").read_text(encoding="utf-8")
    assert "put requested delivery or approval posture on the same create" in claim
    assert "--verification-method browser-inspection" in verify
