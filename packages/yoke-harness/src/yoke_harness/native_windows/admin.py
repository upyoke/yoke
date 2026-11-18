"""Administrator SSH script staging with bounded, nonsecret transport evidence."""

import subprocess
import time
from uuid import uuid4

from yoke_harness.native_windows.framed_process import run_framed
from yoke_harness.native_windows.stdin_frame import frame_bytes, upload_received, upload_script
from yoke_harness.native_windows.transport import encoded, quote
from yoke_harness.test_machine_remote_exec import host_key_options


class AdminScriptError(RuntimeError):
    """Expose only transport metadata; subprocess causes stay private."""

    def __init__(self, code, diagnostics):
        self.code = code
        self.diagnostics = diagnostics
        super().__init__(code)

    def __str__(self):
        return f"{self.code}: owned path {self.diagnostics['owned_path']}; {self.diagnostics}; restore administrator SSH connectivity, inspect causes and primary_result privately, and verify owned staging removal before retrying"


def admin_script(key, host, user, script, *, input_text=None):
    """Retain upload timing and cleanup evidence without exposing scripts or argv."""
    path = rf"C:\ProgramData\YokeQaProvision-{uuid4().hex}.ps1"
    ssh = [
        "ssh", "-F", "none", *host_key_options({}), "-i", str(key),
        "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15", f"{user}@{host}",
    ]
    payload = script.encode("utf-8-sig")
    diagnostics = {
        "phase": "upload", "owned_path": path, "total_bytes": len(payload),
        "total_chunks": (len(payload) + 2047) // 2048,
        "last_verified_offset": 0, "chunks": [], "cleanup": "pending",
    }
    failure = result = None
    try:
        started = time.monotonic()
        deadline = started + 30
        try:
            for offset in range(0, len(payload), 2048):
                chunk = payload[offset:offset + 2048]
                write = upload_script(quote(path), offset=offset)
                before = time.monotonic()
                remaining = deadline - before
                event = {
                    "index": offset // 2048 + 1, "offset": offset, "bytes": len(chunk),
                    "elapsed_seconds": round(before - started, 3),
                    "remaining_seconds": round(max(remaining, 0), 3),
                    "outcome": "started",
                }
                diagnostics["chunks"].append(event)
                try:
                    if remaining <= 0:
                        event["outcome"] = "deadline_exhausted"
                        raise subprocess.TimeoutExpired("Windows script upload", 30)
                    uploaded = run_framed(
                        [*ssh, "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded(write)],
                        input=frame_bytes(chunk), capture_output=True, text=True, timeout=remaining,
                    )
                    if not upload_received(uploaded, payload[:offset + len(chunk)]):
                        event["outcome"] = "receipt_mismatch"
                        error = AdminScriptError("windows_admin_script_upload_failed", diagnostics)
                        error.upload_result = uploaded
                        raise error
                    diagnostics["last_verified_offset"] = offset + len(chunk)
                    event["outcome"] = "verified"
                except AdminScriptError:
                    raise
                except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    event["outcome"] = type(exc).__name__
                    raise AdminScriptError("windows_admin_script_upload_failed", diagnostics) from exc
                finally:
                    event["duration_seconds"] = round(time.monotonic() - before, 3)
        finally:
            diagnostics["upload_elapsed_seconds"] = round(time.monotonic() - started, 3)
        diagnostics["phase"] = "execution"
        execute = run_framed if input_text is not None else subprocess.run
        result = execute(
            [*ssh, "powershell.exe -NoProfile -NonInteractive -File " + path],
            input=frame_bytes(input_text.encode("utf-8")) if input_text is not None else None,
            capture_output=True, text=True, timeout=300,
        )
        result.staging_diagnostics = diagnostics
        return result
    except BaseException as exc:
        failure = exc
        failure.staging_diagnostics = diagnostics
        raise
    finally:
        before = time.monotonic()
        removed = None
        try:
            cleanup = "$ErrorActionPreference='Stop'; Remove-Item -LiteralPath " + quote(path) + " -Force -ErrorAction SilentlyContinue; if(Test-Path -LiteralPath " + quote(path) + "){throw 'owned staging cleanup failed'}"
            removed = subprocess.run(
                [*ssh, "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded(cleanup)],
                capture_output=True, text=True, timeout=30,
            )
            diagnostics["cleanup_exit_code"] = removed.returncode
            if removed.returncode:
                raise RuntimeError("windows_admin_staging_cleanup_failed")
            diagnostics["cleanup"] = "verified_absent"
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            diagnostics["cleanup"] = "cleanup remains unverified"
            diagnostics["cleanup_error_type"] = type(exc).__name__
            if failure is None:
                error = AdminScriptError("windows_admin_staging_cleanup_failed", diagnostics)
                error.primary_result = result
                error.cleanup_result = removed
                raise error from exc
            failure.staging_diagnostics = diagnostics
            failure.staging_cleanup_cause = exc
            failure.cleanup_result = removed
            failure.add_note("Owned Windows staging cleanup failed; inspect staging_diagnostics for the exact owned path.")
        finally:
            diagnostics["cleanup_duration_seconds"] = round(time.monotonic() - before, 3)
