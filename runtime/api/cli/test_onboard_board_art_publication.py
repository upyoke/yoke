"""Setup's board art reaches the remote setup published to, or says why not."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_contracts.project_contract.board_art import generate_default_variants  # noqa: E402
from yoke_cli.config import onboard_apply_report  # noqa: E402
from yoke_cli.config import onboard_publication  # noqa: E402
from yoke_cli.config import onboard_wizard_board_art_apply as art_apply  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardResult  # noqa: E402
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow  # noqa: E402
from yoke_cli.project_install import publication, publication_outcome  # noqa: E402
from yoke_cli.project_install import publication_pull_request  # noqa: E402
from yoke_cli.project_install import runner  # noqa: E402
from yoke_core.domain import json_helper  # noqa: E402

from runtime.api.cli.project_install_publication_test_support import (  # noqa: E402
    PROTECTED_PRE_RECEIVE_HOOK,
    REJECTING_PRE_RECEIVE_HOOK,
    bind_bundle,
    git,
    identify,
    remote_world,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def test_board_art_commit_reaches_an_empty_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, checkout = _empty_remote_clone(tmp_path)
    report, report_path = _published_setup(tmp_path, checkout, monkeypatch)

    assert _BoardArtShell()._board_art_after_apply(report) is True

    head = git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert git(remote, "rev-parse", "main").stdout.strip() == head
    assert git(remote, "log", "-1", "--format=%s", "main").stdout.strip() == (
        art_apply.BOARD_ART_COMMIT_MESSAGE
    )
    outcome = report["project_onboarding"]["install"]["publication"]
    assert outcome["status"] == publication_outcome.PUBLISHED
    assert outcome["commit"] == head
    payload = json_helper.loads_text(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == "done"
    assert _step(payload, onboard_publication.PLAN_ACTION)["detail"]["commit"] == head


def test_refused_board_art_push_is_recorded_pending_with_its_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, checkout = _empty_remote_clone(tmp_path)
    report, report_path = _published_setup(tmp_path, checkout, monkeypatch)
    setup_tip = git(remote, "rev-parse", "main").stdout.strip()
    hook = remote / "hooks" / "pre-receive"
    hook.write_text(REJECTING_PRE_RECEIVE_HOOK, encoding="utf-8")
    hook.chmod(0o755)

    assert _BoardArtShell()._board_art_after_apply(report) is True

    assert git(remote, "rev-parse", "main").stdout.strip() == setup_tip
    outcome = report["project_onboarding"]["install"]["publication"]
    assert outcome["status"] == publication_outcome.PENDING
    assert outcome["recovery"]
    payload = json_helper.loads_text(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == onboard_publication.FINAL_STATUS_PENDING
    step = _step(payload, onboard_publication.PLAN_ACTION)
    assert step["status"] == "incomplete"
    assert step["error"] == outcome["recovery"]


def test_board_art_commit_joins_setup_review_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = remote_world(tmp_path, pre_receive_hook=PROTECTED_PRE_RECEIVE_HOOK)
    opened: list[dict] = []

    def fake_open(slug, *, head_branch, base_branch):
        opened.append({"head": head_branch, "base": base_branch})
        return {"number": 41, "url": "https://github.test/demo/demo/pull/41"}

    monkeypatch.setattr(publication_pull_request, "open_pull_request", fake_open)
    seed_tip = world.remote_tip()
    report, report_path = _published_setup(
        tmp_path,
        world.checkout,
        monkeypatch,
        expect=publication_outcome.PULL_REQUEST_OPEN,
    )
    review = report["project_onboarding"]["install"]["publication"]["proposal_branch"]

    assert _BoardArtShell()._board_art_after_apply(report) is True

    head = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    assert git(world.remote, "rev-parse", review).stdout.strip() == head
    assert world.remote_tip() == seed_tip
    assert len(opened) == 1
    outcome = report["project_onboarding"]["install"]["publication"]
    assert outcome["status"] == publication_outcome.PULL_REQUEST_OPEN
    assert outcome["proposal_branch"] == review
    assert outcome["commit"] == head
    assert outcome["board_art_commit"] == head
    payload = json_helper.loads_text(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == onboard_publication.FINAL_STATUS_PENDING
    assert _step(payload, onboard_publication.PLAN_ACTION)["detail"]["commit"] == head


def test_unpushed_setup_recovery_names_the_board_art_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, checkout = _empty_remote_clone(tmp_path)
    hook = remote / "hooks" / "pre-receive"
    hook.write_text(REJECTING_PRE_RECEIVE_HOOK, encoding="utf-8")
    hook.chmod(0o755)
    report, report_path = _published_setup(
        tmp_path, checkout, monkeypatch, expect=publication_outcome.PENDING
    )

    assert _BoardArtShell()._board_art_after_apply(report) is True

    head = git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert not git(remote, "for-each-ref", "refs/heads").stdout.strip()
    outcome = report["project_onboarding"]["install"]["publication"]
    assert outcome["status"] == publication_outcome.PENDING
    assert outcome["board_art_commit"] == head
    assert head[:12] in outcome["recovery"]
    assert "`git push origin main` publishes the art too" in outcome["recovery"]
    payload = json_helper.loads_text(report_path.read_text(encoding="utf-8"))
    step = _step(payload, onboard_publication.PLAN_ACTION)
    assert step["status"] == "incomplete"
    assert step["error"] == outcome["recovery"]


def _empty_remote_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True
    )
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(checkout)],
        check=True,
        capture_output=True,
    )
    identify(checkout)
    return remote, checkout


def _published_setup(
    tmp_path: Path,
    checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    expect: str = publication_outcome.PUBLISHED,
) -> tuple[dict, Path]:
    """Setup as Apply leaves it: installed, publication tried, report finished."""
    bind_bundle(monkeypatch)
    monkeypatch.setattr(art_apply, "rebuild_board", _write_board_view)
    install = runner.install(
        checkout,
        project_id=7,
        publish_skip_reason=publication_outcome.DEFERRED_REASON,
    )
    install["publication"] = publication.publish_onboarded_layer(
        checkout, install, default_branch="main"
    )
    assert install["publication"]["status"] == expect
    report = {"project_onboarding": {"checkout": str(checkout), "install": install}}
    report_path = tmp_path / "report.json"
    writer = onboard_apply_report.ApplyReportWriter(
        report_path,
        {
            "run_id": "run-test",
            "steps": [
                _planned(
                    f"10-{onboard_publication.PLAN_ACTION}",
                    onboard_publication.PLAN_ACTION,
                ),
                _planned("11-project-write-board-art", art_apply.BOARD_ART_STEP_ACTION),
            ],
            "final_status": None,
            "resume_command": onboard_apply_report.RESUME_COMMAND,
        },
    )
    writer.finish(onboard_publication.record_outcome(writer, report))
    report["apply_report"] = writer.summary()
    return report, report_path


def _planned(step_id: str, action: str) -> dict:
    return {"step_id": step_id, "action": action, "status": "pending"}


def _step(payload: dict, action: str) -> dict:
    return next(step for step in payload["steps"] if step["action"] == action)


def _write_board_view(repo_root: Path) -> Path:
    """Stand in for the board rebuild: an ignored generated view on disk."""
    board = Path(repo_root) / ".yoke" / "BOARD.md"
    board.write_text("board\n", encoding="utf-8")
    return board


class _BoardArtShell(BoardArtFlow):
    def __init__(self) -> None:
        self.result = WizardResult(
            config_path="cfg",
            env_name="prod",
            api_url="https://x",
            project_checkout="",
            board_art_word="EXT",
            board_art_variants=generate_default_variants("EXT", seed_text="seed"),
        )
        self.report_path = None
        self.resume_command = None
