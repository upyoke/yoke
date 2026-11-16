"""Real Windows console input and screen evidence under the test user's token."""

import time
from uuid import uuid4

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.transport import quote

SCREEN_READER = r"""
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class QaConsole {
 [StructLayout(LayoutKind.Sequential)] public struct Coord { public short X,Y; }
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public short L,T,R,B; }
 [StructLayout(LayoutKind.Sequential)] public struct Info { public Coord Size,Cursor; public short Attr; public Rect Window; public Coord Max; }
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool AttachConsole(uint pid);
 [DllImport("kernel32.dll")] static extern bool FreeConsole();
 [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int type);
 [DllImport("kernel32.dll")] static extern bool SetStdHandle(int type,IntPtr value);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetConsoleScreenBufferInfo(IntPtr h,out Info info);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool ReadConsoleOutputCharacterW(IntPtr h,StringBuilder text,uint size,Coord start,out uint read);
 public static string Read(uint pid) {
  var output=GetStdHandle(-11); var input=GetStdHandle(-10); var error=GetStdHandle(-12);
  FreeConsole();
  try {
   if(!AttachConsole(pid)) throw new Exception("windows_console_attach_failed: select Windows Console Host as the default terminal and rerun");
   var handle=GetStdHandle(-11); Info info;
   if(!GetConsoleScreenBufferInfo(handle,out info)) throw new Exception("windows_console_read_failed: keep the native terminal open and retry");
   uint length=(uint)Math.Min(1000000,info.Size.X*(info.Cursor.Y+1));
   var text=new StringBuilder((int)length); uint read;
   if(!ReadConsoleOutputCharacterW(handle,text,length,new Coord(),out read)) throw new Exception("windows_console_read_failed: repair console access and retry");
   var result=new StringBuilder();
   for(int n=0;n<text.Length;n+=info.Size.X) result.AppendLine(text.ToString(n,Math.Min(info.Size.X,text.Length-n)).TrimEnd());
   return result.ToString();
  } finally { FreeConsole(); SetStdHandle(-11,output); SetStdHandle(-10,input); SetStdHandle(-12,error); }
 }
}
"""


class WindowsTerminal:
    def __init__(self, control):
        self.control = control
        self.token = "YokeQa-" + uuid4().hex
        self.pid = None
        self.root = control.home + "\\AppData\\Local\\YokeQa\\" + self.token

    def open(self, entry_surface, size=(120, 40)):
        if not all(1 <= n <= 500 for n in size):
            raise ValueError("terminal size is outside registered bounds")
        script = (
            f"Set-Content -LiteralPath {quote(self.root + '.pid')} -Value $PID; "
            f"$Host.UI.RawUI.WindowTitle={quote(self.token)}; "
            f"$Host.UI.RawUI.BufferSize=[Management.Automation.Host.Size]::new({size[0]},3000); "
            f"$Host.UI.RawUI.WindowSize=[Management.Automation.Host.Size]::new({size[0]},{size[1]}); "
            "try { & { " + entry_surface + " }; "
            "$code=if($null -eq $LASTEXITCODE){0}else{$LASTEXITCODE}; "
            "Write-Host ('__YOKE_EXIT_'+$code) } catch {Write-Host $_; Write-Host '__YOKE_EXIT_1'}"
        )
        self.control.upload_remote_text(self.root + ".ps1", script)
        start = self.control._run(f"""
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoLogo -NoExit -File "'+{quote(self.root + ".ps1")}+'"')
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 40)
Register-ScheduledTask -TaskName {quote(self.token)} -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName {quote(self.token)}
""")
        if start.returncode:
            return False
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            pid = self.control.read_remote_text(self.root + ".pid")
            if pid:
                self.pid = int(pid.strip().lstrip("\ufeff"))
                return True
            time.sleep(0.2)
        return False

    def transcript(self):
        script = "Add-Type -TypeDefinition " + quote(SCREEN_READER)
        result = self.control._run(script + f"; [QaConsole]::Read({self.pid})")
        if result.returncode:
            raise RuntimeError(
                result.stderr
                or "windows_console_read_failed: inspect the native terminal before retrying"
            )
        return result.stdout

    def send(self, text, *, submit=True):
        keys = {
            "Enter": "{ENTER}",
            "C-c": "^c",
            "C-d": "^d",
            "Escape": "{ESC}",
            "Tab": "{TAB}",
            "Up": "{UP}",
            "Down": "{DOWN}",
        }
        value = keys.get(text)
        if value is None:
            value = "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in text)
            if submit:
                value += "{ENTER}"
        sent = desktop_script(
            self.control,
            "$ws=New-Object -ComObject WScript.Shell; "
            f"if(!$ws.AppActivate({self.pid})){{throw 'windows_terminal_focus_failed: unlock the native desktop and retry'}}; "
            "Start-Sleep -Milliseconds 200; "
            f"$ws.SendKeys({quote(value)})",
            timeout=10,
        )
        return sent.returncode == 0

    def wait_for(self, expected, deadline, progress_callback=None):
        values = [expected] if isinstance(expected, str) else expected
        while time.monotonic() < deadline:
            observed = self.transcript()
            if all(value in observed for value in values):
                return observed
            if progress_callback:
                progress_callback()
            time.sleep(0.2)
        return None

    def capture_window(self):
        checkpoint = getattr(self.control, "capture_terminal_checkpoint", None)
        if checkpoint is not None:
            return checkpoint()
        # Full desktop: includes the real console and proves native session use.
        result = self.control.capture_screenshot()
        if not result.ok:
            raise RuntimeError(str(result.evidence))
        return result.evidence

    def close(self):
        result = self.control._run(f"""
if(Get-ScheduledTask -TaskName {quote(self.token)} -ErrorAction SilentlyContinue){{
 Stop-ScheduledTask -TaskName {quote(self.token)}
 Unregister-ScheduledTask -TaskName {quote(self.token)} -Confirm:$false
}}
""")
        if result.returncode:
            return False
        if self.pid is not None:
            stopped = self.control._run(
                f"if(Get-Process -Id {self.pid} -ErrorAction SilentlyContinue){{& taskkill.exe /PID {self.pid} /T /F | Out-Null}}; if(Get-Process -Id {self.pid} -ErrorAction SilentlyContinue){{exit 1}}; exit 0"
            )
            if stopped.returncode:
                return False
        removed = self.control._run(
            f"foreach($p in @({quote(self.root + '.ps1')},{quote(self.root + '.pid')})){{if(Test-Path -LiteralPath $p){{Remove-Item -LiteralPath $p -Force -ErrorAction Stop}}}}"
        )
        return removed.returncode == 0


def run_native_terminal_case(
    control,
    *,
    entry_surface,
    required_completion,
    steps,
    capture_checkpoints=(),
    progress_callback=None,
    size=(120, 40),
    **kwargs,
):
    terminal = WindowsTerminal(control)
    rows = []
    try:
        if not terminal.open(entry_surface, size):
            return HostActionResult(
                False,
                {
                    "recovery": "Log on and unlock the standard test user; select Windows Console Host and retry."
                },
                "windows_terminal_unavailable",
            )
        for step in steps:
            if step.get("send") and not terminal.send(str(step["send"])):
                raise RuntimeError(
                    "windows_terminal_input_failed: unlock and focus the native console before retrying"
                )
            text = terminal.wait_for(
                step["expect"],
                time.monotonic() + int(step.get("timeout_seconds", 30)),
                progress_callback,
            )
            rows.append(
                {
                    "key": step["key"],
                    "ok": text is not None,
                    "reached": text is not None,
                    "transcript": text or "",
                }
            )
            if text is None:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Inspect the native console and the unmet expectation, then rerun.",
                    },
                    "windows_terminal_expectation_timeout",
                )
            if step["key"] in capture_checkpoints:
                rows[-1].update(terminal.capture_window())
        ok = any(row["key"] == required_completion and row["ok"] for row in rows)
        return HostActionResult(
            ok,
            {
                "steps": rows,
                "transcript": terminal.transcript(),
                "terminal_backend": "windows-console",
            },
            None if ok else "terminal_completion_not_proved",
        )
    except RuntimeError as exc:
        return HostActionResult(
            False, {"steps": rows, "recovery": str(exc)}, "windows_terminal_failed"
        )
    finally:
        if not terminal.close():
            raise RuntimeError(
                "windows_terminal_cleanup_failed: stop the test console process tree before releasing the QA lease"
            )
