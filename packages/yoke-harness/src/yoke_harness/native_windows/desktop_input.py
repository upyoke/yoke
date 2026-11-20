"""Drive any native Windows desktop app in the logged-on test user's session.

The request rides inside the uploaded script, which ``desktop_script`` removes
after the run; results keep typed text only as its length.
"""

import base64
import json

from yoke_contracts.desktop_input import refuse_secret_text, validate_request
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.desktop_input_helper import HELPER
from yoke_harness.native_windows.transport import quote

_ASSEMBLIES = "UIAutomationClient,UIAutomationTypes,WindowsBase"
_DISPATCH = r"""
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(REQUEST)) | ConvertFrom-Json
function Element($r) { $t=@{}; foreach($k in 'name','automation_id','control_type','index'){ if($r.element.$k){ $t[$k]=[string]$r.element.$k } }; $t }
function Target($r) { [QaDesktop]::Resolve([string]$r.window.title,[string]$r.window.process,[string]$r.window.handle,[int]$r.wait_seconds) }
try {
  $result = switch ($request.action) {
    'windows' { @{windows=@([QaDesktop]::Windows())} }
    'focus' { @{window=[QaDesktop]::Focus((Target $request))} }
    'keys' { [QaDesktop]::PressKeys((Target $request),[string[]]@($request.keys)) }
    'type' { [QaDesktop]::Type((Target $request),(Element $request),[string]$request.text,[int]$request.wait_seconds) }
    'read' { [QaDesktop]::Read((Target $request),(Element $request),[int]$request.wait_seconds) }
    'click' {
      if ($null -ne $request.x) { [QaDesktop]::ClickAt((Target $request),[int]$request.x,[int]$request.y,[string]$request.button,[bool]$request.double) }
      else { [QaDesktop]::ClickElement((Target $request),(Element $request),[string]$request.button,[bool]$request.double,[int]$request.wait_seconds) }
    }
  }
  $row = @{ok=$true;result=$result}
} catch {
  $message = $_.Exception.Message
  while ($_.Exception.InnerException -and $message -notmatch '^[a-z_]+: ') { $message = $_.Exception.InnerException.Message }
  $row = @{ok=$false;message=$message}
}
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($row | ConvertTo-Json -Depth 8 -Compress)))
"""


def _failure(code, detail, recovery):
    return HostActionResult(False, {"detail": detail, "recovery": recovery}, code)


def drive_desktop(control, raw_request, *, secrets=()):
    """Run one validated action; return its structured result or named refusal."""
    request = validate_request(raw_request)
    if request["action"] == "type":
        refuse_secret_text(request["text"], secrets)
    encoded = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -ReferencedAssemblies {_ASSEMBLIES} -TypeDefinition {quote(HELPER)}\n"
        + _DISPATCH.replace("REQUEST", quote(encoded))
    )
    ran = desktop_script(control, script, timeout=request["wait_seconds"] + 60, hidden=True)
    if ran.returncode == 124:
        return _failure(
            "windows_desktop_task_timeout",
            "the desktop task did not finish",
            "Unlock the auto-logged-on test session, inspect Task Scheduler, then retry",
        )
    try:
        row = json.loads(base64.b64decode(ran.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return _failure(
            "windows_desktop_input_failed",
            (ran.stderr or "the helper printed no result").strip()[:600],
            "Take a screenshot, check the test user's session is unlocked, then retry",
        )
    if row.get("ok"):
        evidence = {"action": request["action"], **(row.get("result") or {})}
        return HostActionResult(True, evidence)
    code, _, detail = str(row.get("message") or "").partition(": ")
    if not code.replace("_", "").isalpha() or not code.islower():
        code, detail = "windows_desktop_input_failed", str(row.get("message"))
    detail, _, recovery = detail.partition("; recovery: ")
    head, sep, tail = detail.rpartition("; ")
    return _failure(
        code,
        head if sep else detail,
        recovery or (tail if sep else "Take a screenshot to see the desktop, then retry"),
    )


__all__ = ["drive_desktop"]
