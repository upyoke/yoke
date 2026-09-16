"""Publishing the install commit, and naming every outcome that is not that."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.install import PUBLICATION_PENDING_EXIT
from yoke_cli.main import main as cli_main
from yoke_cli.project_install import publication_outcome
from yoke_cli.project_install import publication_pull_request
from yoke_cli.project_install import runner

from runtime.api.cli.project_install_publication_test_support import (
    MANAGED_BLOCK,
    OPERATOR_TEXT,
    PROTECTED_PRE_RECEIVE_HOOK,
    REJECTING_PRE_RECEIVE_HOOK,
    bind_bundle,
    git,
    local_only_checkout,
    remote_world,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def test_install_pushes_its_commit_to_the_branch_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)

    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PUBLISHED
    assert publication["remote"] == "origin"
    assert publication["commit"] == report["commit"]["sha"]
    assert world.remote_tip() == report["commit"]["sha"]
    assert world.is_clean()


def test_no_commit_run_publishes_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    before = world.remote_tip()

    report = runner.install(world.checkout, project_id=7, commit=False)

    assert report["publication"] == {
        "status": publication_outcome.SKIPPED, "reason": "no-commit",
    }
    assert world.remote_tip() == before


def test_local_only_checkout_is_a_skip_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = local_only_checkout(tmp_path)
    bind_bundle(monkeypatch)

    report = runner.install(root, project_id=7)

    assert report["publication"] == {
        "status": publication_outcome.SKIPPED,
        "reason": publication_outcome.LOCAL_ONLY_REASON,
    }
    assert report["commit"]["status"] == "created"


def test_no_publish_keeps_the_commit_local_by_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    before = world.remote_tip()

    report = runner.install(world.checkout, project_id=7, publish=False)

    assert report["publication"] == {
        "status": publication_outcome.SKIPPED,
        "reason": publication_outcome.DISABLED_REASON,
    }
    assert report["commit"]["status"] == "created"
    assert world.remote_tip() == before


def test_protected_branch_proposes_the_same_commit_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path, pre_receive_hook=PROTECTED_PRE_RECEIVE_HOOK)
    bind_bundle(monkeypatch)
    opened: list[tuple] = []

    def fake_open(slug, *, head_branch, base_branch):
        opened.append((slug, head_branch, base_branch))
        return {"number": 41, "url": "https://example.invalid/pull/41"}

    monkeypatch.setattr(
        publication_pull_request, "open_pull_request", fake_open,
    )
    protected_tip = world.remote_tip()

    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]
    commit = report["commit"]["sha"]
    assert publication["status"] == publication_outcome.PULL_REQUEST_OPEN
    assert publication["pull_request"] == {
        "number": 41, "url": "https://example.invalid/pull/41",
    }
    assert publication["proposal_branch"] == f"yoke-install/{commit[:12]}"
    assert opened == [("demo", f"yoke-install/{commit[:12]}", "main")]
    assert publication["proposal_branch"] in world.remote_branches()
    assert world.remote_tip() == protected_tip
    assert "git pull --rebase origin main" in publication["recovery"]


def test_unopened_pull_request_still_leaves_the_branch_and_the_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path, pre_receive_hook=PROTECTED_PRE_RECEIVE_HOOK)
    bind_bundle(monkeypatch)
    monkeypatch.setattr(
        publication_pull_request,
        "open_pull_request",
        lambda *_a, **_k: None,
    )

    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PENDING
    assert publication["commit"] == report["commit"]["sha"]
    assert publication["proposal_branch"] in world.remote_branches()
    assert "yoke github pr create" in publication["recovery"]


def test_refused_push_reports_pending_with_commit_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path, pre_receive_hook=REJECTING_PRE_RECEIVE_HOOK)
    bind_bundle(monkeypatch)

    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PENDING
    assert publication["commit"] == report["commit"]["sha"]
    assert "authorize the remote" in publication["recovery"]
    assert "git push origin main" in publication["recovery"]
    assert report["commit"]["status"] == "created"


def test_operator_commits_are_never_published_on_their_behalf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    (world.checkout / "operator.md").write_text("mine\n", encoding="utf-8")
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "operator work in progress")
    before = world.remote_tip()

    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PENDING
    assert "operator work in progress" in publication["detail"]
    assert "publish or drop them yourself" in publication["recovery"]
    assert world.remote_tip() == before
    assert report["commit"]["status"] == "created"


def test_unchanged_bundle_refresh_has_nothing_to_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    runner.install(world.checkout, project_id=7)
    published = world.remote_tip()

    report = runner.refresh(world.checkout, project_id=7)

    assert report["commit"]["status"] == "nothing_to_commit"
    assert report["publication"]["status"] == publication_outcome.ALREADY_PUBLISHED
    assert world.remote_tip() == published


def test_cli_exits_pending_status_when_the_layer_did_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    world = remote_world(tmp_path, pre_receive_hook=REJECTING_PRE_RECEIVE_HOOK)
    bind_bundle(monkeypatch)
    _seed_https_connection(tmp_path)
    capsys.readouterr()

    code = cli_main([
        "project", "install", str(world.checkout),
        "--project-id", "7", "--config", str(_config_path(tmp_path)), "--json",
    ])

    captured = capsys.readouterr()
    assert code == PUBLICATION_PENDING_EXIT
    report = json.loads(captured.out)
    assert report["publication"]["status"] == publication_outcome.PENDING
    assert "INSTALLED LOCALLY, NOT PUBLISHED" in captured.err


def test_cli_exits_zero_when_the_layer_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    _seed_https_connection(tmp_path)
    capsys.readouterr()

    code = cli_main([
        "project", "install", str(world.checkout),
        "--project-id", "7", "--config", str(_config_path(tmp_path)), "--json",
    ])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["publication"]["status"] == (
        publication_outcome.PUBLISHED
    )
    assert world.remote_tip() == json.loads(captured.out)["commit"]["sha"]


def test_source_dev_local_source_apply_publishes_nothing(
    tmp_path: Path, capsys,
) -> None:
    world = remote_world(tmp_path)
    source = Path(__file__).resolve().parents[3]
    capsys.readouterr()

    code = cli_main([
        "project", "refresh", str(world.checkout),
        "--source-checkout", str(source),
        "--project-id", "41", "--project-slug", "preview-project", "--json",
    ])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preview"] is True
    assert "publication" not in report


def test_managed_block_and_operator_text_both_reach_the_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)

    runner.install(world.checkout, project_id=7)

    published = git(
        world.remote, "show", "main:AGENTS.md",
    ).stdout
    assert MANAGED_BLOCK.strip() in published
    assert OPERATOR_TEXT.strip() in published


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / "machine-home" / "config.json"


def _seed_https_connection(tmp_path: Path) -> None:
    """Give the CLI a connection so dispatch does not refuse before install."""
    token = tmp_path / "token"
    token.write_text("t\n", encoding="utf-8")
    assert cli_main([
        "connection", "set", "local",
        "--transport", "https",
        "--api-url", "http://127.0.0.1:1",
        "--token-file", str(token),
        "--config", str(_config_path(tmp_path)),
    ]) == 0
