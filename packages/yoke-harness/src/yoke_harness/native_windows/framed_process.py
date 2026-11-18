"""Send bounded frames without closing SSH stdin before the guest finishes."""

import subprocess
from threading import Thread
import time

from yoke_harness.native_windows.stdin_frame import MAX_ENCODED


def run_framed(argv, *, input, timeout, capture_output=True, text=True):
    """Drain both outputs concurrently; the framed reader never requires EOF.

    The deadline covers process startup and input delivery. A writer thread also
    bounds a full stdin pipe. Local termination/draining has a separate four-
    second reserve; uncertain cleanup is retained on the original exception.
    """
    if not capture_output or not text or not isinstance(input, str) or not input.isascii():
        raise ValueError("windows_framed_input_invalid: provide an ASCII frame")
    if len(input) > MAX_ENCODED + 9:
        raise ValueError("windows_framed_input_too_large: split the payload")
    deadline = time.monotonic() + timeout
    child = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    output = {"stdout": "", "stderr": ""}
    read_errors, write_errors = [], []

    def drain(name):
        try:
            output[name] = getattr(child, name).read()
        except BaseException as exc:
            read_errors.append(exc)

    def write():
        try:
            if child.stdin.write(input) != len(input):
                raise OSError("incomplete framed input write")
            child.stdin.flush()
            # Keep this pipe open until the remote process exits. In particular,
            # do not use communicate(), which sends stdin EOF after its write.
        except BaseException as exc:
            write_errors.append(exc)

    workers = [Thread(target=drain, args=(name,), daemon=True) for name in output]
    workers.append(Thread(target=write, daemon=True))
    failure = None
    try:
        for worker in workers:
            worker.start()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        child.wait(timeout=remaining)
    except BaseException as exc:
        failure = exc
        try:
            child.kill()
            child.wait(timeout=2)
        except (OSError, subprocess.SubprocessError) as cleanup:
            failure.add_note("Local SSH termination unverified: " + type(cleanup).__name__)
    finally:
        drain_deadline = time.monotonic() + 2
        for worker in workers:
            if worker.ident is not None:
                worker.join(timeout=max(0, drain_deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers):
            if failure is None:
                failure = RuntimeError("windows_framed_process_cleanup_unverified")
            else:
                failure.add_note("Local SSH pipe cleanup remains unverified")
        else:
            # Closing a stream while another thread holds its IO lock can block.
            for name in ("stdin", "stdout", "stderr"):
                try:
                    getattr(child, name).close()
                except (OSError, ValueError):
                    pass
    if failure is not None:
        failure.local_process_pid = child.pid
        failure.local_cleanup_verified = child.poll() is not None and not any(worker.is_alive() for worker in workers)
        if isinstance(failure, subprocess.TimeoutExpired):
            failure.stdout, failure.stderr = output["stdout"], output["stderr"]
        if write_errors:
            failure.stdin_write_cause = write_errors[0]
        raise failure
    if read_errors:
        raise RuntimeError("windows_framed_process_capture_failed") from read_errors[0]
    result = subprocess.CompletedProcess(argv, child.returncode, output["stdout"], output["stderr"])
    if write_errors:
        if child.returncode == 0:
            error = RuntimeError("windows_framed_input_incomplete")
            error.primary_result = result
            raise error from write_errors[0]
        result.stdin_write_cause = write_errors[0]
    return result
