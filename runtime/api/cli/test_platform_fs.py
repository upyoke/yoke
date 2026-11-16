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
