"""Transient Windows handles cannot lose native capture envelopes."""

import ctypes
import errno
import os
from pathlib import Path
import threading

import pytest

from yoke_contracts import filesystem_safety, owner_private_path
from yoke_harness import session_relay_native_diagnostics as diagnostics
from yoke_harness import session_relay_native_supervisor as supervisor
from yoke_harness.session_relay_native_capture_format import compose_capture

pytestmark = pytest.mark.windows


def test_capture_read_retries_sharing_violation(monkeypatch, tmp_path):
    path = tmp_path / 'native.capture'
    payload = compose_capture(stdout=b'finished', stderr=b'', state='exited', exit_code=0)
    diagnostics.write_native_capture(path, payload)
    read = Path.read_bytes
    attempts = []

    def busy(selected):
        attempts.append(selected)
        if len(attempts) < 3:
            raise PermissionError(13, 'sharing violation')
        return read(selected)

    monkeypatch.setattr(filesystem_safety, '_RETRY_SHARING_VIOLATIONS', True)
    monkeypatch.setattr(filesystem_safety.time, 'sleep', lambda delay: None)
    monkeypatch.setattr(Path, 'read_bytes', busy)
    capture = diagnostics.read_native_capture(path)
    assert capture.exited and capture.stdout == b'finished'
    assert len(attempts) == 3


def test_final_capture_failure_is_reported_after_retries(monkeypatch, tmp_path, capsys):
    def fail(*args):
        raise diagnostics.NativeDiagnosticError('capture locked')

    monkeypatch.setattr(supervisor, 'write_native_capture', fail)
    supervisor._write(tmp_path / 'native.capture', supervisor.BoundedStreams(), state='exited')
    reported = capsys.readouterr().err
    assert 'native_capture_final_write_failed' in reported
    assert 'capture locked' in reported
    assert 'close open capture handles' in reported


@pytest.mark.windows_only(reason='requires native Windows sharing semantics')
@pytest.mark.parametrize('operation', ['replace', 'read'])
def test_native_windows_capture_lock_records_sharing_error_and_recovers(tmp_path, operation):
    from ctypes import wintypes

    path = tmp_path / 'native.capture'
    payload = compose_capture(stdout=b'finished', stderr=b'', state='exited', exit_code=0)
    diagnostics.write_native_capture(path, payload)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Deny every other open, including delete sharing required by os.replace.
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value
    timer = None
    try:
        with pytest.raises(PermissionError) as failure:
            if operation == 'read':
                path.read_bytes()
            else:
                temporary = tmp_path / 'replacement'
                temporary.write_bytes(payload)
                os.replace(temporary, path)
        # MoveFileEx reports access denied; the CRT read exposes only EACCES.
        assert failure.value.errno == errno.EACCES
        assert failure.value.winerror == (5 if operation == 'replace' else None)
        print(f'{operation}: errno={failure.value.errno} winerror={failure.value.winerror}')
        timer = threading.Timer(0.05, lambda: kernel.CloseHandle(handle))
        timer.start()
        if operation == 'read':
            assert diagnostics.read_native_capture(path).exited
        else:
            owner_private_path.write_owner_private(path, payload)
    finally:
        if timer is None:
            kernel.CloseHandle(handle)
        else:
            timer.join()
    assert diagnostics.read_native_capture(path).exited
