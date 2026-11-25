"""Supervise a scheduled desktop command using only inbox Windows PowerShell."""

from yoke_harness.native_windows.transport import quote

CLEANUP_SECONDS = 5
SCHEDULER_GRACE_SECONDS = 20
TIMEOUT = "windows_desktop_task_timeout"
UNRESOLVED = "windows_desktop_cleanup_unresolved"
RECOVERY = (
    "retain this receipt, inspect Task Scheduler history for the named task and check "
    "the test user's desktop; reset the test machine if ownership cannot be established before retrying"
)

# This runs before the test host has Yoke or its Python packages. Use the same
# Win32 custody as platform_process_windows, inside the interactive token.
_JOB = r"""
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class YokeDesktopJob {
    const uint CreateSuspended = 4, KillOnClose = 0x2000;
    const uint Signalled = 0, WaitTimeout = 258;
    const int BasicAccounting = 1, ExtendedLimits = 9;

    [StructLayout(LayoutKind.Sequential)]
    struct Startup {
        public int size;
        public IntPtr reserved, desktop, title;
        public uint x, y, xSize, ySize, xChars, yChars, fill, flags;
        public ushort show, reservedSize;
        public IntPtr reservedBytes, input, output, error;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo {
        public IntPtr process, thread;
        public uint pid, tid;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits {
        public long processTime, jobTime;
        public uint flags;
        public UIntPtr minWorkingSet, maxWorkingSet;
        public uint activeProcessLimit;
        public UIntPtr affinity;
        public uint priority, scheduling;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct Limits {
        public BasicLimits basic;
        public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes;
        public UIntPtr processMemory, jobMemory, peakProcess, peakJob;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct Accounting {
        public long userTime, kernelTime, periodUser, periodKernel;
        public uint faults, total, active, terminated;
    }

    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern IntPtr CreateJobObject(IntPtr security, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass,
        ref Limits data, int length);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool QueryInformationJobObject(IntPtr job, int infoClass,
        out Accounting data, int length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern bool CreateProcess(string exe, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string cwd,
        ref Startup startup, out ProcessInfo info);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr handle);

    static void Check(bool ok, string operation) {
        if (!ok) {
            int error = Marshal.GetLastWin32Error();
            throw new Win32Exception(error, operation + " failed (Win32 " + error + ")");
        }
    }

    static void SetKillOnClose(IntPtr job, bool enabled) {
        Limits limits = new Limits();
        if (enabled) limits.basic.flags = KillOnClose;
        Check(SetInformationJobObject(job, ExtendedLimits, ref limits, Marshal.SizeOf(limits)),
            "SetInformationJobObject");
    }

    static string StopAndVerify(IntPtr job, int cleanupMs) {
        Check(TerminateJobObject(job, 124), "TerminateJobObject");
        Stopwatch clock = Stopwatch.StartNew();
        do {
            Accounting data;
            Check(QueryInformationJobObject(job, BasicAccounting, out data,
                Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero), "QueryInformationJobObject");
            if (data.active == 0) return "verified_empty";
            Thread.Sleep(50);
        } while (clock.ElapsedMilliseconds < cleanupMs);
        return "owned processes remained active after termination";
    }

    public static string Run(string exe, string worker, long timeoutMs, int cleanupMs) {
        if (timeoutMs <= 0) return "verified_empty";
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        Check(job != IntPtr.Zero, "CreateJobObject");
        ProcessInfo child = new ProcessInfo();
        try {
            SetKillOnClose(job, true);
            Startup startup = new Startup();
            startup.size = Marshal.SizeOf(startup);
            StringBuilder command = new StringBuilder("\"" + exe +
                "\" -NoLogo -NoProfile -File \"" + worker + "\"");
            Check(CreateProcess(exe, command, IntPtr.Zero, IntPtr.Zero, false,
                CreateSuspended, IntPtr.Zero, null, ref startup, out child), "CreateProcess");
            if (!AssignProcessToJobObject(job, child.process)) {
                int error = Marshal.GetLastWin32Error();
                // The command has not run. Dispose of the suspended worker.
                TerminateProcess(child.process, 1);
                throw new Win32Exception(error, "AssignProcessToJobObject failed (Win32 " + error + ")");
            }
            Check(ResumeThread(child.thread) != UInt32.MaxValue, "ResumeThread");
            uint status = WaitForSingleObject(child.process, (uint)timeoutMs);
            if (status == Signalled) {
                // A completed desktop command can deliberately leave an app running.
                SetKillOnClose(job, false);
                return null;
            }
            Check(status == WaitTimeout, "WaitForSingleObject");
            try {
                return StopAndVerify(job, cleanupMs);
            } catch (Win32Exception e) {
                return e.Message;
            }
        } finally {
            if (child.thread != IntPtr.Zero) CloseHandle(child.thread);
            if (child.process != IntPtr.Zero) CloseHandle(child.process);
            CloseHandle(job);
        }
    }
}
"""


def supervisor_script(worker, worker_result, staged, receipt, timeout, task):
    timeout_head = quote(f"{TIMEOUT}: the desktop command exceeded {timeout} seconds")
    unresolved = quote(f"{UNRESOLVED}: task {task}")
    recovery = quote(RECOVERY)
    return f"""$ErrorActionPreference='Stop'
$clock=[Diagnostics.Stopwatch]::StartNew()
try {{
  Add-Type -TypeDefinition {quote(_JOB)}
  $cleanup=[YokeDesktopJob]::Run((Join-Path $PSHOME 'powershell.exe'), {quote(worker)},
      ({timeout * 1000} - $clock.ElapsedMilliseconds), {CLEANUP_SECONDS * 1000})
  if($null -eq $cleanup) {{
    Move-Item -LiteralPath {quote(worker_result)} -Destination {quote(receipt)}
    exit 0
  }}
  $errorText={timeout_head}
  if($cleanup -eq 'verified_empty') {{
    $errorText+='; Windows Job confirmed empty'
  }} else {{
    $errorText+="; " + {unresolved} + " ($cleanup); recovery: " + {recovery}
  }}
  $row=@{{exit_code=124;stdout='';stderr=$errorText;process_cleanup=$cleanup}}
}} catch {{
  $row=@{{exit_code=1;stdout='';stderr=('windows_desktop_job_failed: ' + $_.Exception.Message +
    '; recovery: inspect the test user Task Scheduler job policy and repair the desktop fixture before retrying')}}
}}
$row | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(staged)}
Move-Item -LiteralPath {quote(staged)} -Destination {quote(receipt)}
"""
