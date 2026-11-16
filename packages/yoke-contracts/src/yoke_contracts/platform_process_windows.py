"""Win32 job custody for processes spawned by platform_process."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess

import psutil


class Job:
    """A job keeps descendants addressable; closing it does not kill detached work."""

    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError("process_job_assignment_failed: close conflicting job policy and retry")

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 1):
            raise OSError("process_job_stop_failed: run as the process owner and retry")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


def spawn(argv, kwargs):
    from yoke_contracts.platform_process import GroupHandle

    job = Job()
    flags = kwargs.pop("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP | 4
    process = subprocess.Popen(argv, creationflags=flags, **kwargs)
    try:
        job.assign(process)
        observed = psutil.Process(process.pid)
        stamp = observed.create_time()
        # Start suspended so no child can escape custody before job assignment.
        api = job.api
        api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenThread.restype = wintypes.HANDLE
        api.ResumeThread.argtypes = [wintypes.HANDLE]
        api.ResumeThread.restype = wintypes.DWORD
        threads = observed.threads()
        if not threads:
            raise OSError("process_resume_failed: no initial thread; retry the spawn")
        for thread in threads:
            native = api.OpenThread(2, False, thread.id)
            if not native:
                raise OSError("process_resume_failed: cannot open thread; check account policy")
            try:
                if api.ResumeThread(native) == 0xFFFFFFFF:
                    raise OSError("process_resume_failed: cannot resume thread; check account policy")
            finally:
                api.CloseHandle(native)
        return GroupHandle(process.pid, stamp, ((process.pid, stamp),), process, job)
    except BaseException:
        process.kill()
        process.wait()
        job.close()
        raise
