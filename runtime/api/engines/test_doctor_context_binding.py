"""Doctor context and HTTPS composition inspect the selected source lane."""

import subprocess

from yoke_core.engines import doctor_context, doctor_source_root
from yoke_core.engines.doctor_report import DoctorArgs
from yoke_core.engines.doctor_https_compose import UnavailableControlPlane


def test_context_respects_bound_checkout_without_local_database(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor_context, "self_project_names", lambda conn: frozenset({"7"})
    )

    def unavailable(*args):
        raise AssertionError(
            "A bound source context must not resolve through local SQL"
        )

    monkeypatch.setattr(doctor_context, "checkout_for_project", unavailable)
    with doctor_source_root.bound_source_root(tmp_path):
        context = doctor_context.resolve_context(
            UnavailableControlPlane(), DoctorArgs(project="7", runtime="local")
        )
    assert context.source_checkout == tmp_path


def test_imported_lane_belongs_to_mapped_repository(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "Initial",
        ],
        check=True,
    )
    lane = tmp_path / "lane"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-qb", "candidate", str(lane)],
        check=True,
        capture_output=True,
    )
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setattr(doctor_source_root, "source_checkout_root", lambda _: lane)
    assert doctor_source_root.preferred_source_checkout(main) == lane
    assert doctor_source_root.preferred_source_checkout(other) == other


def test_hosted_runtime_never_uses_client_source_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_context, "self_project_names", lambda conn: frozenset())
    with doctor_source_root.bound_source_root(tmp_path):
        context = doctor_context.resolve_context(
            UnavailableControlPlane(), DoctorArgs(project="other", runtime="hosted")
        )
    assert context.source_checkout is None
