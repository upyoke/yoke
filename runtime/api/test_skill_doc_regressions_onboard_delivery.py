"""Onboard scopes setup and delivery to the first work, then hands it off."""

from runtime.api.skill_doc_regressions_test_helpers import _read

from runtime.api.test_skill_doc_regressions_onboard import ONBOARD_DIR, _onboard_bundle


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_onboard_validates_serving_runtime_before_enabling_a_flow() -> None:
    text = _flat(_read(ONBOARD_DIR / "hosting-and-environments.md"))
    assert "execution_supported=false" in text
    assert "creates it disabled, no default" in text
    assert (
        "yoke workflows delivery-default set --project {project} "
        "--workflow {workflow} --flow {flow_id}"
    ) in text
    assert "never `--apply-to-all`" in text
    # Task stays exempt: only these four workflows take the default.
    assert "Set the default for dash, issue, epic and blitz" in text
    # A merge-only default delivers at merge without a deployment run.
    assert "two `auto` stages, `merged` and `complete`" in text
    assert "no tier or environment" in text


def test_strategy_step_confirms_the_scan_before_drafting():
    text = _read(ONBOARD_DIR / "strategy-conversation.md")
    flat = _flat(text)
    assert flat.index("name what you will scan") < flat.index("Draft;")
    assert "yoke github open-work list --project {project} --json" in text
    # Transcript stores are harness manifest facts, never restated paths.
    assert "harness manifest" in flat
    assert "~/.claude" not in text and "~/.codex" not in text
    assert "ask what else belongs" in flat
    assert "one at a time, the first work last" in flat


def test_setup_steps_defer_what_the_first_work_does_not_need():
    router = _flat(_read(ONBOARD_DIR / "SKILL.md"))
    assert "Steps 2–7 run only for what the first work needs" in router
    assert "write their rows `deferred`" in router
    assert "Never switch projects" in router


def test_handoff_routes_filing_through_steering():
    text = _read(ONBOARD_DIR / "first-work.md")
    assert "Onboarding files no items" in text
    assert "/yoke steer CURRENT-PLAN" in text
    assert "yoke items create" not in _onboard_bundle()
    assert "yoke qa item-plan attach --item {ITEM}" in text
    assert "installer-campaign plan" in text
    assert "write both rows" in text
    # Activation is observed, never written.
    assert "--row-status lifecycle-readiness" not in _onboard_bundle()
    assert "`lifecycle-readiness` reading verified" in text
