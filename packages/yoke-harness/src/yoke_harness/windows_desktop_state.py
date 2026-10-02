"""Read active Windows logins through WTS, independently of localized CLI text."""

import base64
import json
import shlex

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

# Native PowerShell module initialization can exceed 15 seconds after boot.
SESSION_QUERY_TIMEOUT = 45


SESSION_SCRIPT = r"""$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class YokeSessions {
  [StructLayout(LayoutKind.Sequential)] struct Session {
    public int Id; public IntPtr Station; public int State;
  }
  [DllImport("wtsapi32.dll", SetLastError=true)] static extern bool WTSEnumerateSessions(IntPtr server, int reserved, int version, out IntPtr data, out int count);
  [DllImport("wtsapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool WTSQuerySessionInformation(IntPtr server, int id, int info, out IntPtr data, out int size);
  [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr data);
  public class Login { public int session_id; public string user; }
  public static Login[] Active() {
    IntPtr data; int count;
    if (!WTSEnumerateSessions(IntPtr.Zero, 0, 1, out data, out count)) throw new System.ComponentModel.Win32Exception();
    var result = new List<Login>();
    try {
      int stride = Marshal.SizeOf(typeof(Session));
      for (int i=0; i<count; i++) {
        var s = (Session)Marshal.PtrToStructure(IntPtr.Add(data, i*stride), typeof(Session));
        if (s.State != 0 || s.Id <= 0) continue;
        IntPtr user; int size;
        if (!WTSQuerySessionInformation(IntPtr.Zero, s.Id, 5, out user, out size)) throw new System.ComponentModel.Win32Exception();
        try {
          string name = Marshal.PtrToStringUni(user);
          if (!String.IsNullOrEmpty(name)) result.Add(new Login {session_id=s.Id, user=name});
        } finally { WTSFreeMemory(user); }
      }
    } finally { WTSFreeMemory(data); }
    return result.ToArray();
  }
}
'@
ConvertTo-Json -Compress -InputObject @([YokeSessions]::Active())
"""


def active_windows_sessions(control):
    from yoke_harness.desktop_access import DesktopAccessError

    encoded = base64.b64encode(SESSION_SCRIPT.encode("utf-16-le")).decode("ascii")
    result = control._run(
        "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
        + shlex.quote(encoded),
        timeout=SESSION_QUERY_TIMEOUT,
    )
    try:
        sessions = json.loads(result.stdout.lstrip("\ufeff"))
        if result.returncode or not isinstance(sessions, list):
            raise ValueError("session probe refused")
        for session in sessions:
            if int(session["session_id"]) <= 0 or not isinstance(session["user"], str):
                raise ValueError("invalid login")
        return sessions
    except (KeyError, TypeError, ValueError):
        secrets = getattr(control, "secret_values", ())
        stdout = bounded_machine_qa_diagnostic(result.stdout, secrets)
        stderr = bounded_machine_qa_diagnostic(getattr(result, "stderr", ""), secrets)
        raise DesktopAccessError(
            f"windows_desktop_state_unknown: query exit={result.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}; "
            "repair the SSH account's Windows WTS session query, then retry; no RDP login was started"
        ) from None
