"""Resume retains read-only intent until an explicit destination choice."""

from types import SimpleNamespace

from yoke_cli.commands.adapters.onboard import _parser
from yoke_cli.config import onboard_apply_resume, onboard_apply_snapshot
from yoke_cli.config.onboard_wizard_flow_apply import ApplyFlow
from yoke_cli.config.project_clone_support import ClonePlan
from runtime.api.cli.test_onboard_publication_receipts import setup_read_only


def test_snapshot_restores_layer_keep_but_never_replays_removal():
    snapshot = onboard_apply_snapshot.build(
        {
            "project_checkout": "/project",
            "project_clone": ClonePlan(existing_layer_decision="keep"),
        }
    )
    parsed = _parser().parse_args([])
    onboard_apply_resume.apply_defaults(parsed, snapshot)
    assert parsed.project_existing_yoke_layer == "keep"
    snapshot["project"]["clone"]["existing_layer_decision"] = "remove"
    parsed = _parser().parse_args([])
    onboard_apply_resume.apply_defaults(parsed, snapshot)
    assert parsed.project_existing_yoke_layer is None
    snapshot["project"]["clone"]["existing_layer_decision"] = "keep"
    other = _parser().parse_args(["--checkout", "/another-project"])
    onboard_apply_resume.apply_defaults(other, snapshot)
    assert other.project_existing_yoke_layer is None


def test_explicit_destination_overrides_saved_read_only_without_replacing_other_defaults():
    snapshot = onboard_apply_snapshot.build(
        {
            "project_checkout": "/project",
            "project_default_branch": "main",
            "project_clone": ClonePlan(
                outcome="just-clone", existing_layer_decision="keep"
            ),
        }
    )
    resumed = _parser().parse_args([])
    onboard_apply_resume.apply_defaults(resumed, snapshot)
    assert resumed.project_clone_outcome == "just-clone"
    explicit = _parser().parse_args(["--publication-destination", "source"])
    onboard_apply_resume.apply_defaults(explicit, snapshot)
    assert explicit.project_clone_outcome == "source"
    assert explicit.project_checkout == "/project"
    assert explicit.project_existing_yoke_layer == "keep"


def test_verified_same_run_layer_defaults_keep_but_foreign_project_does_not(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    world, writer, _, _ = setup_read_only(tmp_path, monkeypatch)
    parsed = SimpleNamespace(
        project_existing_yoke_layer=None,
        project_checkout=str(world.checkout),
        project_default_branch="main",
        existing_project_id=7,
    )
    onboard_apply_resume.restore_owned_layer_choice(parsed, writer.payload)
    assert parsed.project_existing_yoke_layer == "keep"
    parsed.project_existing_yoke_layer = None
    parsed.existing_project_id = 8
    onboard_apply_resume.restore_owned_layer_choice(parsed, writer.payload)
    assert parsed.project_existing_yoke_layer is None
    parsed.existing_project_id = 7
    parsed.project_existing_yoke_layer = "remove"
    onboard_apply_resume.restore_owned_layer_choice(parsed, writer.payload)
    assert parsed.project_existing_yoke_layer == "remove"


def test_wizard_resume_reopens_destination_instead_of_replaying_read_only(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    world, writer, _, _ = setup_read_only(tmp_path, monkeypatch)
    shell = SimpleNamespace(
        report_path=str(writer.path),
        result=SimpleNamespace(
            project_checkout=str(world.checkout),
            project_default_branch="main",
            existing_project_id=7,
            project_clone_existing_layer_decision="remove",
        ),
    )
    called = []
    shell._goto_clone_outcome = lambda: called.append("choose-destination")
    shell._start_apply = lambda: called.append("apply")
    shell._show_apply_recovery_error = lambda error: called.append(str(error))
    ApplyFlow._resume_apply_from_report(shell)
    assert called == ["choose-destination"]
    assert shell._resume_run_id == writer.payload["run_id"]
    assert shell.result.project_clone_existing_layer_decision == "keep"
