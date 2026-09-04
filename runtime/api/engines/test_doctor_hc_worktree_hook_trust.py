"""Doctor coverage for normalized Codex hook trust in linked worktrees."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from yoke_core.domain.codex_hook_trust_identity import codex_hook_hashes
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_worktree_hook_trust as check


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_HOOKS = _REPO_ROOT / "runtime/harness/codex/hooks.json"


def _checkout(root: Path) -> Path:
    hooks = root / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_bytes(_CURRENT_HOOKS.read_bytes())
    return root


def _write_trust(config: Path, checkouts: tuple[Path, ...]) -> None:
    lines = ['model = "gpt-5.6-luna"\n']
    for checkout in checkouts:
        hooks = checkout / ".codex/hooks.json"
        for suffix, digest in sorted(codex_hook_hashes(hooks).items()):
            lines.extend(
                [
                    f'\n[hooks.state."{hooks}:{suffix}"]\n',
                    f'trusted_hash = "{digest}"\n',
                ]
            )
    config.write_text("".join(lines), encoding="utf-8")


def _seed(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = _checkout(tmp_path / "checkout")
    worktree = _checkout(source / ".worktrees/lane")
    config = tmp_path / "config.toml"
    _write_trust(config, (source, worktree))
    return source, worktree, config


def test_main_checkout_resolves_common_git_directory(monkeypatch, tmp_path: Path):
    source = tmp_path / "checkout"
    lane = source / ".worktrees/lane"
    common_dir = source / ".git"
    monkeypatch.setattr(
        check,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, f"{common_dir}\n", ""
        ),
    )

    assert check._main_checkout(str(lane)) == str(source)


def _run(
    monkeypatch,
    source: Path,
    worktree: Path | None,
    config: Path,
):
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: source)
    monkeypatch.setattr(
        check,
        "_linked_worktrees",
        lambda _root: [str(worktree)] if worktree is not None else [],
    )
    monkeypatch.setattr(check, "codex_config_path", lambda: config)
    records = RecordCollector()
    check.hc_worktree_hook_trust(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_current_codex_hook_config_has_matching_trust(monkeypatch, tmp_path: Path):
    source, worktree, config = _seed(tmp_path)

    result = _run(monkeypatch, source, worktree, config)

    assert result.result == "PASS", result.detail


def test_command_edit_marks_persisted_trust_modified(monkeypatch, tmp_path: Path):
    source, worktree, config = _seed(tmp_path)
    hooks = worktree / ".codex/hooks.json"
    document = json.loads(hooks.read_text(encoding="utf-8"))
    handler = document["hooks"]["SessionStart"][0]["hooks"][0]
    handler["command"] += " changed"
    hooks.write_text(json.dumps(document), encoding="utf-8")

    result = _run(monkeypatch, source, worktree, config)

    assert result.result == "FAIL"
    assert "modified" in result.detail
    assert "session_start:0:0" in result.detail


def test_main_checkout_mismatch_fails_with_codex_retrust_recovery(
    monkeypatch, tmp_path: Path
):
    source, worktree, config = _seed(tmp_path)
    hooks = source / ".codex/hooks.json"
    document = json.loads(hooks.read_text(encoding="utf-8"))
    document["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " changed"
    hooks.write_text(json.dumps(document), encoding="utf-8")

    result = _run(monkeypatch, source, worktree, config)

    assert result.result == "FAIL"
    assert "main checkout" in result.detail
    assert f"open Codex in {source}, Hooks, Trust" in result.detail


def test_main_checkout_is_checked_without_linked_worktrees(monkeypatch, tmp_path: Path):
    source, _worktree, config = _seed(tmp_path)

    result = _run(monkeypatch, source, None, config)

    assert result.result == "PASS", result.detail
    assert "main checkout carries exact hook trust" in result.detail


def test_missing_codex_config_fails_main_checkout_with_recovery(
    monkeypatch, tmp_path: Path
):
    source = _checkout(tmp_path / "checkout")
    config = tmp_path / "missing-config.toml"

    result = _run(monkeypatch, source, None, config)

    assert result.result == "FAIL"
    assert "Codex config not present" in result.detail
    assert f"open Codex in {source}, Hooks, Trust" in result.detail


def test_deleted_paths_warn_with_sweep_recovery(monkeypatch, tmp_path: Path):
    source, worktree, config = _seed(tmp_path)
    gone = tmp_path / "deleted-lane"
    with config.open("a", encoding="utf-8") as handle:
        handle.write(
            f'''\n[hooks.state."{gone}/.codex/hooks.json:session_start:0:0"]
trusted_hash = "stale"

[projects."{gone}"]
trust_level = "trusted"
'''
        )

    result = _run(monkeypatch, source, worktree, config)

    assert result.result == "WARN"
    assert "1 hook entries across 1 deleted hooks paths" in result.detail
    assert "1 deleted project entries" in result.detail
    assert "yoke codex hook-trust sweep" in result.detail
