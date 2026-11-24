"""Probe a cold-booted native Windows console through the standard SSH account."""

import base64

CONSOLE_MISSING = "windows_console_session_missing"
CONSOLE_MISSING_EXIT = 3

_PROBE = r"""
$ProgressPreference='SilentlyContinue'
function Refuse-MissingConsole {
    [Console]::Error.WriteLine('windows_console_session_missing')
    exit 3
}
# quser can exit 1 even when it lists users. Read its rows and diagnostics.
$output=@(& "$env:SystemRoot\System32\quser.exe" 2>&1)
if ($output.Count -eq 1 -and $output[0].ToString().Trim() -eq 'No User exists for *') {
    Refuse-MissingConsole
}
$errors=@($output | Where-Object { $_ -is [Management.Automation.ErrorRecord] })
if ($errors.Count) {
    [Console]::Error.WriteLine(($errors -join [Environment]::NewLine))
    exit 1
}
if ($output.Count -lt 2) {
    [Console]::Error.WriteLine('quser returned no session table')
    exit 1
}
$consoleSession=$null
foreach ($row in ($output | Select-Object -Skip 1)) {
    # Disconnected rows have no session name. The state column is localized.
    if ($row -notmatch '^\s*>?\s*(\S+)\s+(?:(\S+)\s+)?([0-9]+)\s+\S+(?:\s+.*)?$') {
        [Console]::Error.WriteLine('quser returned an unparseable session row')
        exit 1
    }
    if ($Matches[1] -eq $testUser -and $Matches[2] -eq 'console') {
        $consoleSession=[int]$Matches[3]
    }
}
if ($null -ne $consoleSession -and
    (Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -eq $consoleSession)) {
    exit 0
}
Refuse-MissingConsole
"""


def windows_console_readiness_command(account: str) -> str:
    user = account.rsplit("\\", 1)[-1].replace("'", "''")
    script = f"$testUser='{user}'\n" + _PROBE
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
