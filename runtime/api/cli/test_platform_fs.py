"""Removal handles read-only entries and names the locked file on exhaustion."""
import stat

import pytest
from yoke_contracts import platform_fs


def test_readonly_tree_removed(tmp_path):
    root = tmp_path / 'tree'
    root.mkdir()
    data = root / 'readonly'
    data.write_bytes(b'data')
    data.chmod(stat.S_IREAD)
    root.chmod(stat.S_IREAD | stat.S_IEXEC)
    platform_fs.remove_tree(root)
    assert not root.exists()
    platform_fs.remove_tree(root)


def test_locked_path_names_recovery(monkeypatch, tmp_path):
    root = tmp_path / 'tree'
    root.mkdir()
    locked = str(root / 'locked')
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise PermissionError(13, 'busy', locked)
    monkeypatch.setattr(platform_fs.shutil, 'rmtree', fail)
    monkeypatch.setattr(platform_fs.time, 'sleep', lambda _: None)
    with pytest.raises(OSError, match='remove_tree_locked: .*locked; close'):
        platform_fs.remove_tree(root)
    assert len(calls) == 4


def test_junction_root_is_removed_without_walking_target(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    root = tmp_path / 'junction'
    root.mkdir()
    lstat = Path.lstat
    removed = []
    def junction_info(path):
        info = lstat(path)
        if path == root:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, 'lstat', junction_info)
    monkeypatch.setattr(Path, 'rmdir', lambda path: removed.append(path))
    monkeypatch.setattr(platform_fs.shutil, 'rmtree', lambda *a, **k: pytest.fail('must not walk a junction'))
    platform_fs.remove_tree(root)
    assert removed == [root]
