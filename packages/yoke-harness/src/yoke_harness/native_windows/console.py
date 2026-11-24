"""Prove the dedicated lab account owns an unlocked physical console session."""

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.desktop_geometry import is_desktop_resolution
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.display_geometry import DEFINITION

RECOVERY = (
    "Check autologon in the VM console and repair Windows desktop provisioning if needed. "
    "If an RDP viewer is connected, disconnect without signing out and retry."
)
PROBE = r"""
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class YokeConsoleProbe {
 [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId();
 [DllImport("user32.dll")] static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)]
 static extern bool GetUserObjectInformation(IntPtr handle,int index,StringBuilder value,int size,out int needed);
 [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr handle);
 public static bool InputDesktopReady() {
  IntPtr handle=OpenInputDesktop(0,false,1); // DESKTOP_READOBJECTS
  if(handle==IntPtr.Zero) return false;
  try {
   var name=new StringBuilder(64); int needed;
   return GetUserObjectInformation(handle,2,name,name.Capacity*2,out needed)
          && name.ToString()=="Default";
  } finally { CloseDesktop(handle); }
 }
}
'@
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if ($session -eq 0 -or $session -ne [YokeConsoleProbe]::WTSGetActiveConsoleSessionId() -or
    !(Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -eq $session)) {
 throw 'windows_console_session_missing: check autologon in the VM console and repair Windows desktop provisioning'
}
if (![YokeConsoleProbe]::InputDesktopReady()) {
 throw 'windows_console_locked: reconnect to the lab account, unlock and disconnect before retrying'
}
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$pixel=[Drawing.Bitmap]::new(1,1)
$graphics=[Drawing.Graphics]::FromImage($pixel)
try {
 $graphics.CopyFromScreen([Windows.Forms.SystemInformation]::VirtualScreen.Location,[Drawing.Point]::Empty,$pixel.Size)
} finally { $graphics.Dispose(); $pixel.Dispose() }
"""
# WTS enumeration may be filtered by session permissions. Require visibility
# into every interactive Winlogon session before treating an empty user as proof.
SIGNED_OUT_PROBE = r"""
Add-Type @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class YokeWindowsSessions {
 [StructLayout(LayoutKind.Sequential)]
 public struct Session {
  public int EnvironmentId, State, Id;
  public IntPtr Name, Host, User, Domain, Farm;
 }
 enum BufferType { ProcessLevel0, ProcessLevel1, SessionLevel1 }
 const int Disconnected=4;
 [DllImport("wtsapi32.dll", SetLastError=true, ExactSpelling=true)]
 static extern bool WTSEnumerateSessionsExW(IntPtr server, ref int level, int filter,
                                           out IntPtr buffer, out int count);
 [DllImport("wtsapi32.dll", ExactSpelling=true)]
 static extern bool WTSFreeMemoryExW(BufferType type, IntPtr buffer, int count);
 [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
 public static bool SignedOut(int[] winlogonSessions) {
  int level=1, count;
  IntPtr buffer;
  if (!WTSEnumerateSessionsExW(IntPtr.Zero, ref level, 0, out buffer, out count))
   throw new Win32Exception(Marshal.GetLastWin32Error());
  try {
   var seen=new HashSet<int>();
   for (int i=0; i<count; i++) {
    var row=(Session)Marshal.PtrToStructure(
        IntPtr.Add(buffer, i*Marshal.SizeOf(typeof(Session))), typeof(Session));
    if (row.Id==0) continue;
    if (row.User!=IntPtr.Zero || row.State==Disconnected) return false;
    seen.Add(row.Id);
   }
   return seen.Contains(unchecked((int)WTSGetActiveConsoleSessionId()))
       && winlogonSessions.Length>0 && seen.IsSupersetOf(winlogonSessions);
  } finally { WTSFreeMemoryExW(BufferType.SessionLevel1, buffer, count); }
 }
}
'@
$sessions=@(Get-Process -Name winlogon -ErrorAction Stop | Select-Object -ExpandProperty SessionId)
if ([YokeWindowsSessions]::SignedOut([int[]]$sessions)) { 'YOKE_WINDOWS_SIGNED_OUT' }
"""
WSL_PROBE = r"""
& wsl.exe --cd '~' -e /usr/bin/true
if ($LASTEXITCODE -ne 0) {
 throw 'windows_console_wsl_unavailable: repair the SSH account default distro and rerun provisioning'
}
"""
RECEIPT = "YOKE_WINDOWS_CONSOLE_READY"
PROBE_TIMEOUT = 30


def probe_console(control, *, wsl=False, set_resolution=False, retry=False):
    method = "Ensure" if set_resolution else "Observe"
    geometry = DEFINITION + f"Write-Output ([YokeDesktopGeometry]::{method}())\n"
    script = PROBE + (WSL_PROBE if wsl else geometry) + f"\nWrite-Output '{RECEIPT}'"
    try:
        wait = {"announce_wait": False} if retry else {}
        completed = desktop_script(control, script, timeout=PROBE_TIMEOUT, **wait)
    except RuntimeError as exc:
        detail = str(exc)
    else:
        lines = completed.stdout.strip().splitlines()
        resolution = lines[-2] if len(lines) >= 2 else None
        if (
            completed.returncode == 0 and lines[-1:] == [RECEIPT]
            and (wsl or is_desktop_resolution(resolution))
        ):
            evidence = {"desktop_session": "windows_console", "wsl_started": wsl}
            if not wsl:
                evidence["resolution"] = resolution
            return HostActionResult(True, evidence)
        detail = completed.stderr.strip() or "Interactive task did not return its console receipt."
    return HostActionResult(
        False,
        {"diagnostic": detail[-1200:], "recovery": RECOVERY},
        "windows_console_not_ready",
    )


def verify_console(control, check_bridge, *, wsl=False):
    console = probe_console(control, wsl=wsl)
    if not console.ok:
        return console
    bridge = check_bridge()
    return HostActionResult(
        bridge.ok, {**bridge.evidence, "windows_console": console.evidence}, bridge.error_code
    )
