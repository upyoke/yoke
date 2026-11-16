"""Link fallbacks preserve data and refuse existing destinations."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from yoke_contracts import platform_links as links
from yoke_contracts.platform_fs import remove_tree


def test_link_and_remove_do_not_follow_target(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data').write_text('hello', encoding='utf-8')
    destination = tmp_path / 'link'
    assert links.link(source, destination) in {'symlink', 'junction', 'copy'}
    assert (destination / 'data').read_text(encoding='utf-8') == 'hello'
    with pytest.raises(FileExistsError, match='link_destination_exists'):
        links.link(source, destination)
    remove_tree(destination)
    assert (source / 'data').exists()


def test_windows_copy_fallback(monkeypatch, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data').write_bytes(b'hello')
    destination = tmp_path / 'copy'
    monkeypatch.setattr(links, 'os', SimpleNamespace(name='nt', environ={}, path=links.os.path))
    monkeypatch.setattr(Path, 'symlink_to', lambda *a, **k: (_ for _ in ()).throw(OSError('privilege')))
    monkeypatch.setattr(links.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    assert links.link(source, destination) == 'copy'
    assert (destination / 'data').read_bytes() == b'hello'


def test_missing_target_refuses(tmp_path):
    with pytest.raises(FileNotFoundError, match='link_target_missing'):
        links.link(tmp_path / 'missing', tmp_path / 'link')
