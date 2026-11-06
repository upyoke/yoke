"""Project-scoped onboarding resumes and immutable run ownership."""

import pytest

from runtime.api.domain.project_onboarding_runs_test_support import _conn
from yoke_core.domain import project_onboarding_runs as runs


def test_resume_without_run_id_selects_its_own_project():
    with _conn() as conn:
        first = runs.init_run(conn=conn, project_id=7)
        other = runs.init_run(conn=conn, project_id=11)
        resumed = runs.init_run(conn=conn, project_id=7)
        assert resumed["run_id"] == first["run_id"]
        assert resumed["run_id"] != other["run_id"]
        assert resumed["resumed"] is True


@pytest.mark.parametrize("selected_project", [11, None])
def test_explicit_foreign_run_refuses_before_mutation(selected_project):
    with _conn() as conn:
        original = runs.init_run(conn=conn, project_id=7, checkout_path="/repo")
        with pytest.raises(runs.ProjectOnboardingRunError, match="project_mismatch"):
            runs.update_run(
                conn=conn,
                run_id=original["run_id"],
                project_id=selected_project,
                checkout_path="/other",
                row_status={"strategy-setup": "verified"},
            )
        saved = runs.get_run(original["run_id"], conn=conn)
        assert saved == original["run"]


def test_raced_run_owner_refuses_before_choices_are_written(monkeypatch):
    from yoke_core.domain import project_onboarding_updates as writes

    with _conn() as conn:
        original = runs.init_run(conn=conn, project_id=7)
        monkeypatch.setattr(writes, "resolve_run", lambda *args, **kwargs: (original["run_id"], None))
        with pytest.raises(runs.ProjectOnboardingRunError, match="project_mismatch"):
            runs.update_run(
                conn=conn, project_id=11, run_id=original["run_id"],
                metadata={"execution_profile": {"hosting": "deferred"}},
            )
        assert runs.get_run(original["run_id"], conn=conn) == original["run"]
