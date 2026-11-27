"""Link fallbacks preserve data and refuse existing destinations."""
import ntpath
from pathlib import Path
from types import SimpleNamespace

import pytest
from yoke_contracts import platform_links as links
from yoke_contracts.platform_fs import remove_tree


pytestmark = pytest.mark.windows


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


def test_junction_false_copies_where_symlinks_are_refused(monkeypatch, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data').write_bytes(b'hello')
    destination = tmp_path / 'copy'
    monkeypatch.setattr(links, 'os', SimpleNamespace(name='nt', environ={}, path=links.os.path))
    monkeypatch.setattr(Path, 'symlink_to', lambda *a, **k: (_ for _ in ()).throw(OSError('privilege')))

    def no_junction(*args, **kwargs):
        raise AssertionError('mklink /J must not run when junction=False')

    monkeypatch.setattr(links.subprocess, 'run', no_junction)
    assert links.link(source, destination, junction=False) == 'copy'
    assert (destination / 'data').read_bytes() == b'hello'


@pytest.mark.windows_only(reason="requires native Windows junctions")
def test_windows_directory_link_creates_junction_without_symlink_privilege(monkeypatch, tmp_path):
    source = tmp_path / "source directory"
    source.mkdir()
    data = source / "data.txt"
    data.write_text("original", encoding="utf-8")
    destination = tmp_path / "junction directory"

    def deny_symlink(*args, **kwargs):
        raise PermissionError("symlink privilege unavailable")

    monkeypatch.setattr(Path, "symlink_to", deny_symlink)
    try:
        assert links.link(source, destination) == "junction"
        assert destination.is_junction()
        assert destination.resolve() == source.resolve()
        assert links.link_target(destination) == source.absolute()
        assert links.resolve_links(destination) == source.resolve()
        links.remove_link(destination)
        assert not destination.exists()
        assert data.read_text(encoding="utf-8") == "original"
    finally:
        if destination.is_junction():
            links.remove_link(destination)
        elif destination.exists():
            remove_tree(destination)


@pytest.mark.parametrize("recorded, expected", [
    ("\\\\?\\C:\\Users\\me\\shared", "C:\\Users\\me\\shared"),
    ("\\\\?\\UNC\\server\\share\\shared", "\\\\server\\share\\shared"),
    ("C:\\Users\\me\\shared", "C:\\Users\\me\\shared"),
])
def test_recorded_target_reads_the_windows_record_without_traversing(monkeypatch, recorded, expected):
    def untraversable(*args, **kwargs):
        raise OSError(22, "untrusted mount point (WinError 448)")
    monkeypatch.setattr(Path, "resolve", untraversable)
    monkeypatch.setattr(links, "os", SimpleNamespace(name="nt", path=ntpath, readlink=lambda path: recorded))
    assert links._recorded_target(Path("yoke-global")) == expected


def test_missing_target_refuses(tmp_path):
    with pytest.raises(FileNotFoundError, match='link_target_missing'):
        links.link(tmp_path / 'missing', tmp_path / 'link')


def test_concurrent_destination_is_never_overwritten(monkeypatch, tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.write_bytes(b'source')
    def collision(path, *args, **kwargs):
        path.write_bytes(b'other caller')
        raise FileExistsError(str(path))
    monkeypatch.setattr(Path, 'symlink_to', collision)
    with pytest.raises(FileExistsError, match='link_destination_exists'):
        links.link(source, destination)
    assert destination.read_bytes() == b'other caller'


def test_file_copy_fallback_refuses_racing_destination(monkeypatch, tmp_path):
    import builtins
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.write_bytes(b'source')
    def no_symlinks(*args, **kwargs):
        raise OSError('unsupported filesystem')
    original_open = builtins.open
    def racing_open(path, mode, *args, **kwargs):
        if Path(path) == destination and mode == 'xb':
            destination.write_bytes(b'other caller')
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'symlink_to', no_symlinks)
    monkeypatch.setattr(links, 'open', racing_open, raising=False)
    with pytest.raises(FileExistsError, match='link_destination_exists'):
        links.link(source, destination)
    assert destination.read_bytes() == b'other caller'
