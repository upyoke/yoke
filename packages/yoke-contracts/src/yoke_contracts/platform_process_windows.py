"""Win32 job custody for processes spawned by platform_process."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess

import psutil


class Job:
    """A job keeps descendants addressable; closing it does not kill detached work."""

    def __init__(self):
        self.handle = None
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

    def kill_on_close(self):
        """End every member once the last handle to this job closes.

        The creator's death closes its handle, so members cannot outlive it.
        """
        class Basic(ctypes.Structure):
            _fields_ = [("user_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_set", ctypes.c_size_t),
                        ("max_set", ctypes.c_size_t), ("processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6)]
            _fields_ += [(name, ctypes.c_size_t) for name in (
                "process_memory", "job_memory", "peak_process", "peak_job")]
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        apply = self.api.SetInformationJobObject
        apply.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        apply.restype = wintypes.BOOL
        if not apply(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError("process_job_limit_failed: close conflicting job policy and retry")
        return self

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 1):
            raise OSError("process_job_stop_failed: run as the process owner and retry")

    def has_active_processes(self):
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in (
                "total_user", "total_kernel", "period_user", "period_kernel")]
            _fields_ += [(name, wintypes.DWORD) for name in (
                "faults", "total", "active", "terminated")]
        accounting = Accounting()
        query = self.api.QueryInformationJobObject
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.c_void_p]
        query.restype = wintypes.BOOL
        if not query(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
            raise OSError("process_job_inspection_failed: run as its owner and retry")
        return bool(accounting.active)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


def popen_in_job(argv, kwargs, job):
    """Start *argv* suspended, assign it to *job*, then resume it.

    Starting suspended means no descendant can escape the job's custody.
    """
    flags = kwargs.pop("creationflags", 0) | 4  # CREATE_SUSPENDED
    process = subprocess.Popen(argv, creationflags=flags, **kwargs)
    try:
        job.assign(process)
        _resume(process, job.api)
    except BaseException:
        process.kill()
        process.wait()
        raise
    return process


def _resume(process, api):
    """Resume every thread of a process started with CREATE_SUSPENDED."""
    api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenThread.restype = wintypes.HANDLE
    api.ResumeThread.argtypes = [wintypes.HANDLE]
    api.ResumeThread.restype = wintypes.DWORD
    threads = psutil.Process(process.pid).threads()
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


def spawn(argv, kwargs):
    from yoke_contracts.platform_process import GroupHandle

    job = Job()
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        process = popen_in_job(argv, kwargs, job)
        stamp = psutil.Process(process.pid).create_time()
        return GroupHandle(process.pid, stamp, ((process.pid, stamp),), process, job)
    except BaseException:
        job.close()
        raise
