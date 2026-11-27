"""Link-aware containment answers without traversing any link.

A native Windows SSH session may refuse to traverse a directory junction its
user made (WinError 448). ``resolve_links`` reads each link's recorded target
instead, so project install's containment check works there. Here every
``Path.resolve``/``os.path.realpath`` is refused to prove nothing follows a link.
On Windows the directory links are junctions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_cli.project_install.files import assert_resolved_targets_within
from yoke_contracts import platform_links as links
from yoke_contracts.project_contract.install_error import ProjectInstallError

windows_smoke = pytest.mark.windows


def _deny_symlink(*args, **kwargs):
    raise PermissionError("symlink privilege unavailable")


def _dir_link(target: Path, path: Path, monkeypatch) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with monkeypatch.context() as patch:
        if os.name == "nt":
            patch.setattr(Path, "symlink_to", _deny_symlink)
        assert links.link(target, path) in {"symlink", "junction"}


def _refuse_traversal(monkeypatch) -> None:
    def untrusted(*args, **kwargs):
        raise OSError(22, "untrusted mount point (WinError 448)")

    monkeypatch.setattr(Path, "resolve", untrusted)
    monkeypatch.setattr(os.path, "realpath", untrusted)


def _checkout(tmp_path: Path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "checkout"
    (root / ".agents" / "skills" / "yoke").mkdir(parents=True)
    return root


@windows_smoke
def test_resolve_links_follows_records_like_resolve(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    link = root / ".claude" / "skills" / "yoke"
    _dir_link(root / ".agents" / "skills" / "yoke", link, monkeypatch)
    expected = (link / "SKILL.md").resolve(strict=False)
    _refuse_traversal(monkeypatch)

    assert links.resolve_links(link / "SKILL.md") == expected
    assert links.resolve_links(root / "absent" / "file") == root / "absent" / "file"


@windows_smoke
def test_project_skill_link_inside_root_passes_without_traversal(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    _dir_link(root / ".agents" / "skills" / "yoke", root / ".claude" / "skills" / "yoke", monkeypatch)
    _refuse_traversal(monkeypatch)

    assert_resolved_targets_within(
        root, [".claude/skills/yoke", ".claude/skills/yoke/SKILL.md"], context="install recovery checkout"
    )


@windows_smoke
def test_link_escaping_root_is_still_refused_without_traversal(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    outside = Path(os.path.realpath(tmp_path)) / "outside"
    outside.mkdir()
    _dir_link(outside, root / ".claude" / "skills" / "yoke", monkeypatch)
    _refuse_traversal(monkeypatch)

    with pytest.raises(ProjectInstallError, match="resolves outside repo root"):
        assert_resolved_targets_within(
            root, [".claude/skills/yoke/SKILL.md"], context="install recovery checkout"
        )


@windows_smoke
def test_unreadable_link_refuses_with_its_recovery(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    _dir_link(root / ".agents" / "skills" / "yoke", root / ".claude" / "skills" / "yoke", monkeypatch)

    def denied(path):
        raise PermissionError(13, "Access is denied", os.fspath(path))

    monkeypatch.setattr(links, "_recorded_target", denied)

    with pytest.raises(ProjectInstallError, match="cannot be resolved safely.*rerun yoke project refresh"):
        assert_resolved_targets_within(root, [".claude/skills/yoke"], context="install recovery checkout")


@pytest.mark.posix_only(reason="a directory symlink loop needs symlink privilege on Windows")
def test_link_loop_refuses(tmp_path):
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    with pytest.raises(RuntimeError, match="link_loop"):
        links.resolve_links(loop / "x")


@windows_smoke
def test_discovery_link_state_reads_without_traversal(tmp_path, monkeypatch):
    from yoke_cli.project_install import recovery_checkout, skill_discovery

    root = _checkout(tmp_path)
    link = root / ".claude" / "skills" / "yoke"
    _dir_link(root / ".agents" / "skills" / "yoke", link, monkeypatch)
    _refuse_traversal(monkeypatch)

    assert skill_discovery.entry_state(root, ".claude/skills/yoke") == skill_discovery.LINKED
    assert recovery_checkout.state(link) == "link:" + str(root / ".agents" / "skills" / "yoke")
    skill_discovery.preflight(root)


@windows_smoke
def test_dotdot_after_a_link_answers_as_resolve_does(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    (base / "real" / "sub").mkdir(parents=True)
    (base / "real" / "x").mkdir()
    (base / "x").mkdir()
    link = base / "hop"
    _dir_link(base / "real" / "sub", link, monkeypatch)
    expected = (link / ".." / "x").resolve(strict=False)
    _refuse_traversal(monkeypatch)

    assert links.resolve_links(link / ".." / "x") == expected
    # POSIX follows the link before "..", Win32 collapses ".." first.
    assert expected == (base / "x" if os.name == "nt" else base / "real" / "x")


@pytest.mark.posix_only(reason="a relative directory symlink needs symlink privilege on Windows")
def test_relative_record_with_dotdot_after_a_link_answers_as_resolve_does(tmp_path):
    base = Path(os.path.realpath(tmp_path))
    (base / "real" / "sub").mkdir(parents=True)
    (base / "real" / "target").mkdir()
    (base / "hop").symlink_to(base / "real" / "sub")
    (base / "entry").symlink_to(Path("hop") / ".." / "target")

    assert links.resolve_links(base / "entry") == (base / "entry").resolve()
    assert links.resolve_links(base / "entry") == base / "real" / "target"
