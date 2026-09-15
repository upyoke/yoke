"""Onboard delivery configuration teaches runtime-safe flow defaults."""

from runtime.api.skill_doc_regressions_test_helpers import _read

from runtime.api.test_skill_doc_regressions_onboard import ONBOARD_DIR, _onboard_bundle


def test_onboard_validates_serving_runtime_before_enabling_a_flow() -> None:
    text = _onboard_bundle()
    assert "yoke deployment-flows validate --project {project}" in text
    assert "execution_supported=false" in text
    assert "--status disabled" in text
    assert "yoke workflows delivery-default set --project {project} --workflow dash" in text
    assert "Never `--apply-to-all`" in text
    assert "Task stays exempt" in text
    assert "yoke workflows mechanics get --json" in text
    assert "do not invent a stage environment" in text
    assert "ephemeral-env" in text
    for workflow in ("dash", "issue", "epic", "blitz"):
        assert (
            f"yoke workflows delivery-default set --project {{project}} "
            f"--workflow {workflow} --flow {{project}}-merge-only"
        ) in text
    assert "leftover workflow-specific row overrides" in text


def test_onboard_profile_keeps_task_exempt_and_preview_guarded() -> None:
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    assert "yoke workflows delivery-default set" in text
    assert "never `--apply-to-all`" in text
    assert "execution_supported=true" in text
