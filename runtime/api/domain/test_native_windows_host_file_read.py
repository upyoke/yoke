"""Windows host file reads name their real cause; desktop receipts publish whole."""

import json
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.transport import WindowsTransport

pytestmark = pytest.mark.windows

PATH = r"C:\Users\qa\AppData\Local\YokeQa\receipt.json"


def _transport(result):
    transport = WindowsTransport.__new__(WindowsTransport)
    transport.secret_values = ("private-secret",)
    transport._run = lambda script, **kw: result
    return transport


def test_failed_read_names_path_exit_and_stderr_without_acl_advice():
    stderr = "The process cannot access the file because it is being used by another process private-secret"
    transport = _transport(subprocess.CompletedProcess([], 1, "", stderr))

    with pytest.raises(HostControlLocalError) as error:
        transport.read_remote_text(PATH)

    assert error.value.code == "windows_host_file_read_failed"
    assert error.value.phase == "file_read"
    assert PATH in error.value.detail
    assert "exit_code=1" in error.value.detail
    assert "being used by another process [REDACTED]" in error.value.detail
    assert "private-secret" not in error.value.detail
    assert "ACL" not in error.value.recovery_hint


def test_missing_file_still_reads_as_none():
    assert _transport(subprocess.CompletedProcess([], 0, "", "")).read_remote_text(PATH) is None


def test_desktop_receipt_is_staged_then_moved_and_cleanup_owns_the_stage():
    uploads, scripts = {}, []

    class Control:
        home = r"C:\Users\qa"

        def upload_remote_text(self, path, text):
            uploads[path] = text

        def _run(self, script, **kw):
            scripts.append(script)
            return subprocess.CompletedProcess([], 0, "", "")

        def read_remote_text(self, path):
            return json.dumps({"exit_code": 0, "stdout": "ok", "stderr": ""})

    result = desktop_script(Control(), "Write-Output ok", timeout=5)

    assert result.returncode == 0
    command_path = next(path for path in uploads if path.endswith(".command.ps1"))
    root = command_path.removesuffix(".command.ps1")
    supervisor = uploads[root + ".ps1"]
    worker = uploads[root + ".worker.ps1"]
    receipt, worker_result = root + ".json", root + ".worker.json"
    staged = receipt + ".tmp"
    assert f"Set-Content -Encoding UTF8 '{worker_result}'" in worker
    assert f"Move-Item -LiteralPath '{worker_result}' -Destination '{receipt}'" in supervisor
    assert supervisor.index(f"Set-Content -Encoding UTF8 '{staged}'") < supervisor.index(
        f"Move-Item -LiteralPath '{staged}' -Destination '{receipt}'"
    )
    for script in (supervisor, worker):
        assert f"Set-Content -Encoding UTF8 '{receipt}'" not in script
    for path in (worker_result, staged):
        assert f"'{path}'" in scripts[-1]
