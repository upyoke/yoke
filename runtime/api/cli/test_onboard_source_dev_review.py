"""Review and validation coverage for ``Edit Yoke source``."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard_plan_labels
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_report
from yoke_cli.config import yoke_dev_detect


def test_source_activation_has_plain_language_review_label() -> None:
    line = onboard_plan_labels.friendly_line(
        "activate-yoke-source",
        "/src/my-yoke",
    )
    assert line == "Set up the Yoke source checkout at /src/my-yoke"


def test_source_review_plan_uses_checkout_and_optional_clone_url(
    tmp_path: Path,
) -> None:
    checkout = str(tmp_path / "my-yoke")
    plan = onboard_report.build_plan(
        tmp_path / "config.json",
        "prod",
        "https://api.example.test",
        {"kind": "token_file", "path": "/tmp/token"},
        {"kind": "token_file", "path": "/tmp/token"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
        project_inputs={
            "checkout": checkout,
            "remote_url": "https://github.com/example/my-yoke.git",
        },
        machine_github={"choice": "skip"},
    )
    source_steps = [
        step
        for step in plan["steps"]
        if step["action"] in {"clone-yoke-source", "activate-yoke-source"}
    ]
    assert source_steps == [
        {"action": "clone-yoke-source", "target": checkout},
        {"action": "activate-yoke-source", "target": checkout},
    ]


def test_source_review_plan_adds_same_host_server_build(tmp_path: Path) -> None:
    checkout = str(tmp_path / "yoke")
    plan = onboard_report.build_plan(
        tmp_path / "config.json",
        "prod",
        "https://api.example.test",
        {"kind": "token_file", "path": "/tmp/token"},
        {"kind": "token_file", "path": "/tmp/token"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
        project_inputs={"checkout": checkout},
        machine_github={"choice": "skip"},
        same_host_self_host=True,
    )
    assert {
        "action": "run-yoke-server-from-source",
        "target": checkout,
    } in plan["steps"]


def test_source_next_steps_do_not_invent_terminal_restart(tmp_path: Path) -> None:
    steps = onboard_report.next_steps(
        tmp_path / "config.json",
        onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
    )
    assert steps == [f"yoke status --config {tmp_path / 'config.json'}"]


def test_source_checkout_detection_accepts_a_fork_layout(tmp_path: Path) -> None:
    checkout = tmp_path / "my-yoke-fork"
    (checkout / "runtime" / "harness").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    assert yoke_dev_detect.preflight_dev_checkout(str(checkout)) is None


def test_source_checkout_preflight_refuses_non_yoke_folder(tmp_path: Path) -> None:
    conflict = tmp_path / "not-yoke"
    conflict.mkdir()
    (conflict / "README.md").write_text("not yoke\n", encoding="utf-8")
    error = yoke_dev_detect.preflight_dev_checkout(str(conflict))
    assert error is not None
    assert "already has files" in error
    assert "not a Yoke source checkout" in error
