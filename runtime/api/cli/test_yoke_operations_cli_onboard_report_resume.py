"""Resume-aware onboarding report: a re-run names what it reused vs did fresh.

The clone apply is resumable and idempotent, but used to be silent about it — a
re-run that reused a prior partial run's work read exactly like a first run.
These pin the report's two voices:

* a fresh apply renders the original lines, with no "Resumed from a prior run:"
  block (so fresh-run output stays byte-identical);
* a resumed apply (clone present / repo reused / origin already re-homed) renders
  the warm "Reused…" / "already existed — reused" / "Re-pushed…" lines.

Both the report-render seam (:func:`onboard_report.render_human`) and the
flag-projection seam (:func:`project_onboard_support.clone_resume_report`) are
covered directly so the resume signal is asserted end to end without standing up
the full HTTP onboarding flow.
"""

from __future__ import annotations

from typing import Any

from yoke_cli.config import onboard_report
from yoke_cli.config import project_onboard_support as support
from yoke_cli.config.project_onboard_clone import CloneApplyResult


def _applied_report_with(clone_resume: dict[str, bool] | None) -> dict[str, Any]:
    """A minimal applied onboarding report shaped like ``build_report`` emits."""
    project_onboarding: dict[str, Any] = {
        "operation": "project.import",
        "applied": True,
        "project": {
            "github_repo": "octocat/widgets",
            "default_branch": "main",
        },
        "checkout": {"path": "/home/dev/widgets"},
        "handoff": {"run_id": "run-7", "agent_command": "/yoke onboard-project"},
    }
    if clone_resume is not None:
        project_onboarding["clone_resume"] = clone_resume
    return {
        "operation": "onboard",
        "mode": "quick",
        "project_mode": "clone-remote",
        "applied": True,
        "config": "/home/dev/.yoke/config.json",
        "config_path": "/home/dev/.yoke/config.json",
        "plan": {"steps": []},
        "identity": {"checked": False, "ok": None},
        "machine_github": {"choice": "skip"},
        "project_onboarding": project_onboarding,
        "next_steps": ["yoke status"],
    }


def test_fresh_report_has_no_resume_block() -> None:
    rendered = onboard_report.render_human(_applied_report_with(None))
    assert "Resumed from a prior run:" not in rendered
    # None of the resumed-voice lines leak into a fresh run.
    assert "Reused your existing clone" not in rendered
    assert "already existed — reused" not in rendered
    assert "Re-pushed" not in rendered


def test_resumed_report_names_what_was_reused() -> None:
    rendered = onboard_report.render_human(_applied_report_with({
        "clone_reused": True,
        "repo_reused": True,
        "origin_rehomed": True,
    }))
    assert "Resumed from a prior run:" in rendered
    assert "Reused your existing clone at /home/dev/widgets" in rendered
    assert "Repo octocat/widgets already existed — reused" in rendered
    assert "Re-pushed main (resuming a prior run)" in rendered


def test_resumed_report_renders_only_the_steps_that_were_reused() -> None:
    # A resume that only reused the clone (the repo was freshly created this run)
    # names just that line — the repo/origin lines stay out.
    rendered = onboard_report.render_human(_applied_report_with({
        "clone_reused": True,
        "repo_reused": False,
        "origin_rehomed": False,
    }))
    assert "Resumed from a prior run:" in rendered
    assert "Reused your existing clone at /home/dev/widgets" in rendered
    assert "already existed — reused" not in rendered
    assert "Re-pushed" not in rendered


def test_clone_resume_report_is_none_without_an_outcome() -> None:
    assert support.clone_resume_report(None) is None


def test_clone_resume_report_is_none_on_a_fresh_run() -> None:
    # A fresh apply has every flag False — no block is attached, so the report
    # stays byte-identical to a first run.
    fresh = CloneApplyResult(github_repo="octocat/widgets", branch="main")
    assert support.clone_resume_report(fresh) is None


def test_clone_resume_report_carries_flags_on_a_resumed_run() -> None:
    resumed = CloneApplyResult(
        github_repo="octocat/widgets",
        branch="main",
        clone_reused=True,
        repo_reused=True,
        origin_rehomed=True,
    )
    assert support.clone_resume_report(resumed) == {
        "clone_reused": True,
        "repo_reused": True,
        "origin_rehomed": True,
    }
