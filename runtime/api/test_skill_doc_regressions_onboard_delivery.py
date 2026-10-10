"""Onboard delivery configuration teaches runtime-safe flow defaults."""

from runtime.api.skill_doc_regressions_test_helpers import _read

from runtime.api.test_skill_doc_regressions_onboard import ONBOARD_DIR, _onboard_bundle


def test_onboard_validates_serving_runtime_before_enabling_a_flow() -> None:
    text = " ".join(_onboard_bundle().split())
    assert "yoke deployment-flows validate --project {project}" in text
    assert "execution_supported=false" in text
    assert "create disabled, never assign default/advanced preview" in text
    assert (
        "yoke workflows delivery-default set --project {project} --workflow dash"
        in text
    )
    assert "never --apply-to-all" in text
    assert "Task exempt" in text
    assert "yoke workflows mechanics get --json" in text
    assert (
        "Actual non-web/non-Yoke targets need no invented stage/preview environment"
        in text
    )
    assert "ephemeral-env" in text
    for workflow in ("dash", "issue", "epic", "blitz"):
        assert (
            f"yoke workflows delivery-default set --project {{project}} "
            f"--workflow {workflow} --flow {{project}}-merge-only"
        ) in text
    assert "all four workflow defaults, which override project default" in text
    # A merge-only default delivers; it does not exempt the item from the
    # stages its pinned definition declares on the way to done.
    assert "discharges delivery at merge" in text
    assert "no deployment run" in text


def test_onboard_profile_keeps_task_exempt_and_preview_guarded() -> None:
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    assert "hosting-and-environments.md" in text
    owner = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert "yoke workflows delivery-default set" in owner
    assert "Task exempt: never --apply-to-all" in owner
    assert "execution_supported=true" in text
