"""Project uninstall retires the trust lane provisioning granted under the checkout."""

from pathlib import Path

from yoke_contracts import harness_folder_trust as trust
from yoke_contracts.codex_config_posture import parse_config
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_cli.project_install.uninstall import uninstall
from runtime.api.cli.project_uninstall_test_support import read_json
from runtime.api.cli.test_project_uninstall_owned_cleanup import (  # noqa: F401
    installed,
)

DIGEST = "sha256:" + "0" * 64


def _mirror_hook_trust(*checkouts: Path) -> None:
    """Append hook trust shaped like lane provisioning's mirror."""
    config = Path.home() / ".codex/config.toml"
    blocks = "".join(
        f'\n[hooks.state."{checkout}/.codex/hooks.json:session_start:0:0"]\n'
        f'trusted_hash = "{DIGEST}"\n'
        for checkout in checkouts
    )
    config.write_text(config.read_text() + blocks)


def test_uninstall_removes_root_and_lane_trust(installed):  # noqa: F811
    root, other, config = installed
    lane = root / ".worktrees" / "lane-one"
    lane.mkdir(parents=True)
    (root / ".git/info/exclude").write_text(".worktrees/\n")
    other_lane = other / ".worktrees" / "lane-two"
    other_lane.mkdir(parents=True)
    grant_folder_trust(lane)
    grant_folder_trust(other_lane)
    _mirror_hook_trust(lane, other_lane)

    report = uninstall(root, config_path=config)

    assert report["outcome"] == "complete", report
    claude_projects = read_json(trust.claude_state_path())["projects"]
    assert str(root) not in claude_projects and str(lane) not in claude_projects
    assert str(other_lane) in claude_projects
    codex = parse_config((Path.home() / ".codex/config.toml").read_text())
    assert str(root) not in codex["projects"] and str(lane) not in codex["projects"]
    assert str(other_lane) in codex["projects"]
    hook_paths = {key.rsplit(":", 3)[0] for key in codex["hooks"]["state"]}
    assert hook_paths == {f"{other_lane}/.codex/hooks.json"}
    assert not trust.cursor_trust_file(root).exists()
    assert not trust.cursor_trust_file(lane).exists()
    assert trust.cursor_trust_file(other_lane).exists()
    assert any(
        row["reason"] == "lane_hook_trust" and row["status"] == "removed"
        for row in report["local_cleanup"]["trust"]
    )
