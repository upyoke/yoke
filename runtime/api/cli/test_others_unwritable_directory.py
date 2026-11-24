"""Config parents allow shared reads without granting foreign write access."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
from types import SimpleNamespace

import pytest

from yoke_contracts import owner_private_path as paths
from yoke_contracts import windows_others_unwritable_directory as windows
from yoke_contracts import windows_private_directory as private
from yoke_cli.config import machine_config_file
from yoke_cli.config import github_git_credential_bundle as bundle
from yoke_cli.config import github_prior_runtime_verification as prior
from yoke_cli.config.github_git_credential_permissions import assert_secure_parent

@pytest.mark.posix_only(reason="POSIX permissions contract")
def test_posix_parent_permissions_and_owner(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    assert paths.is_others_unwritable_directory(tmp_path)
    assert not paths.is_owner_private_directory(tmp_path)
    for mode in (0o775, 0o757):
        tmp_path.chmod(mode)
        assert not paths.is_others_unwritable_directory(tmp_path)
    tmp_path.chmod(0o700)
    monkeypatch.setattr(paths.os, 'getuid', lambda: tmp_path.stat().st_uid + 1)
    assert not paths.is_others_unwritable_directory(tmp_path)
    assert not paths.is_current_user_owned_path(tmp_path)


@pytest.mark.windows
def test_parent_predicate_refuses_files_links_and_missing(tmp_path):
    path = tmp_path / 'file'
    path.touch()
    assert not paths.is_others_unwritable_directory(path)
    assert not paths.is_others_unwritable_directory(tmp_path / 'missing')
    if os.name != 'nt':
        link = tmp_path / 'link'
        link.symlink_to(tmp_path, target_is_directory=True)
        assert not paths.is_others_unwritable_directory(link)


@pytest.mark.posix_only(reason="POSIX file mode contract")
def test_file_writability_preserves_system_owned_readable_files(tmp_path, monkeypatch):
    path = tmp_path / 'python'
    path.write_text('interpreter', encoding='utf-8')
    monkeypatch.setattr(paths.os, 'getuid', lambda: path.stat().st_uid + 1)
    for mode, accepted in ((0o755, True), (0o644, True), (0o775, False), (0o666, False)):
        path.chmod(mode)
        assert paths.is_others_unwritable_file(path) is accepted
    link = tmp_path / 'link'
    link.symlink_to(path)
    assert not paths.is_others_unwritable_file(link)
    assert not paths.is_others_unwritable_file(tmp_path)


def _check_acl(entries, *, foreign=True, failed_index=None, any_access=False):
    buffers = [ctypes.create_string_buffer(bytes(entry)) for entry in entries]
    acl = windows._Acl(count=len(entries))
    def get_ace(dacl, index, output):
        if index == failed_index:
            return 0
        output._obj.value = ctypes.addressof(buffers[index])
        return 1
    api = SimpleNamespace(
        GetAce=get_ace,
        IsValidAcl=lambda dacl: True,
        IsValidSid=lambda sid: ctypes.c_ubyte.from_address(sid).value == 1,
    )
    original = private._sid_string
    private._sid_string = lambda *args: 'foreign' if foreign else 'user'
    try:
        return windows._acl_has_only_trusted_grants(
            ctypes.cast(ctypes.byref(acl), ctypes.c_void_p),
            {'user'}, api, None, any_access=any_access,
        )
    finally:
        private._sid_string = original


def _ace(mask, *, flags=0, kind=0, object_flags=0):
    body = struct.pack('<I', mask)
    if kind in (5, 11):
        body += struct.pack('<I', object_flags)
        body += b'\0' * (16 * bool(object_flags & 1) + 16 * bool(object_flags & 2))
    body += struct.pack('<BB6sI', 1, 1, (5).to_bytes(6, 'big'), 18)
    return struct.pack('<BBH', kind, flags, 4 + len(body)) + body


@pytest.mark.windows
@pytest.mark.parametrize('mask', [0x2, 0x4, 0x10, 0x40, 0x100, 0x10000,
                                  0x40000, 0x80000, 0x40000000, 0x10000000])
def test_foreign_write_classes_refuse_even_when_inherited(mask):
    assert not _check_acl([_ace(mask, flags=0x10)])
    assert _check_acl([_ace(mask)], foreign=False)
    assert _check_acl([_ace(mask, flags=0x08)])


@pytest.mark.windows
@pytest.mark.parametrize('kind', [0, 5, 9, 11])
def test_allow_ace_layouts_honor_sid_and_read_grants(kind):
    assert not _check_acl([_ace(0x2, kind=kind, object_flags=3)])
    assert _check_acl([_ace(0x120089, kind=kind, object_flags=3)])
    assert _check_acl([_ace(0x2, kind=kind, object_flags=3)], foreign=False)


@pytest.mark.windows
def test_acl_walk_fails_closed_and_does_not_subtract_denies():
    assert _check_acl([])
    assert not _check_acl([_ace(0x2)], failed_index=0)
    assert not _check_acl([_ace(0x2, kind=1), _ace(0x2)])
    assert not _check_acl([_ace(0x2, kind=99)])


@pytest.mark.windows
@pytest.mark.parametrize('flags', [0, 0x08, 0x10])
@pytest.mark.parametrize('mask', [0, 0x120089])
def test_owner_private_acl_refuses_foreign_grants_regardless_of_mask(mask, flags):
    assert not _check_acl([_ace(mask, flags=flags)], any_access=True)
    assert _check_acl([_ace(mask, flags=flags)], foreign=False, any_access=True)


@pytest.mark.windows
def test_owner_private_acl_rejects_truncated_sid_before_rendering():
    malformed = bytearray(_ace(0x120089))
    malformed[9] = 2  # The entry contains only one SID subauthority.
    assert not _check_acl([malformed], foreign=False, any_access=True)


def _set_acl(path, grants, *, owner=None):
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    private._configure_apis(advapi, kernel)
    user = private._current_user_sid(advapi, kernel)
    descriptor = ctypes.c_void_p()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    set_security = advapi.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    sddl = (f'O:{owner or user}D:P(A;OICI;FA;;;{user})'
            f'(A;OICI;FA;;;SY)(A;OICI;FA;;;BA){grants}')
    assert convert(sddl, 1, ctypes.byref(descriptor), None)
    try:
        assert set_security(str(path), 0x80000005, descriptor)
    finally:
        kernel.LocalFree(descriptor)


@pytest.mark.windows
@pytest.mark.windows_only(reason='native Windows DACL contract')
def test_inherited_normal_parent_supports_machine_and_credential_writes(tmp_path):
    parent = paths.create_owner_private_directory(tmp_path / 'owned')
    inherited = parent / 'normal'
    inherited.mkdir()
    assert not paths.is_owner_private_directory(inherited)
    assert paths.is_others_unwritable_directory(inherited)
    assert_secure_parent(inherited, RuntimeError, require_private=False)
    with pytest.raises(RuntimeError, match='permissions are unsafe'):
        assert_secure_parent(inherited, RuntimeError)
    target = inherited / 'config.json'
    with machine_config_file.exclusive_lock(target):
        machine_config_file.atomic_write_text(target, '{}')
    assert paths.is_owner_private_file(target)
    assert paths.is_owner_private_file(machine_config_file.config_lock_path(target))


@pytest.mark.windows
@pytest.mark.windows_only(reason='native Windows DACL contract')
@pytest.mark.parametrize('principal', ['BU', 'WD'])
@pytest.mark.parametrize('grants,accepted', [('(A;;FW;;;{sid})', False),
                                           ('(A;;FR;;;{sid})', True),
                                           ('(A;OICIIO;FW;;;{sid})', True)])
def test_native_foreign_grants(tmp_path, principal, grants, accepted):
    path = paths.create_owner_private_directory(tmp_path / 'parent')
    _set_acl(path, grants.format(sid=principal))
    assert paths.is_others_unwritable_directory(path) is accepted
    if not accepted:
        with pytest.raises(RuntimeError, match="remove other users' write access"):
            assert_secure_parent(path, RuntimeError, require_private=False)
        with pytest.raises(machine_config_file.MachineConfigFileError,
                           match="remove other users' write access"):
            machine_config_file._assert_secure_parent(path)


@pytest.mark.windows
@pytest.mark.windows_only(reason='native Windows file DACL contract')
@pytest.mark.parametrize('principal', ['BU', 'WD'])
@pytest.mark.parametrize('right,accepted', [('FW', False), ('FR', True)])
def test_native_file_foreign_grants(tmp_path, principal, right, accepted):
    path = tmp_path / 'launcher.py'
    paths.write_owner_private(path, b'launcher')
    _set_acl(path, f'(A;;{right};;;{principal})')
    assert paths.is_others_unwritable_file(path) is accepted


@pytest.mark.windows
@pytest.mark.windows_only(reason='native Windows prior-runtime DACL contract')
@pytest.mark.parametrize('target', ['interpreter', 'helper'])
@pytest.mark.parametrize('principal', ['BU', 'WD'])
@pytest.mark.parametrize('right,accepted', [('FW', False), ('FR', True)])
def test_prior_runtime_recognition_honors_native_write_grants(
    tmp_path, target, principal, right, accepted,
):
    helper = bundle.install(tmp_path / 'site')
    python = tmp_path / 'prior-python.exe'
    paths.write_owner_private(python, b'interpreter')
    path = python if target == 'interpreter' else helper
    _set_acl(path, f'(A;;{right};;;{principal})')
    assert prior.verified_prior_runtime_helper(
        python, helper, current_python=tmp_path / 'current-python.exe',
    ) is accepted


@pytest.mark.windows
@pytest.mark.windows_only(reason='native Windows DACL contract')
def test_native_foreign_owner_refuses(tmp_path):
    path = paths.create_owner_private_directory(tmp_path / 'parent')
    try:
        _set_acl(path, '', owner='BA')
    except AssertionError:
        pytest.skip('setting a different owner requires an elevated Windows token')
    try:
        assert not paths.is_current_user_owned_path(path)
        assert not paths.is_others_unwritable_directory(path)
    finally:
        _set_acl(path, '')
