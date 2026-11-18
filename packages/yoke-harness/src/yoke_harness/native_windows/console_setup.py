"""Provision a fixed console-return task and desktop policy for one lab account."""

import base64


VALIDATE_ACCOUNT_PASSWORD = r"""
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class YokeConsoleLogon {
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
 public static extern bool LogonUser(string user,string domain,string password,int type,int provider,out IntPtr token);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr token);
}
'@
$token=[IntPtr]::Zero
if (![YokeConsoleLogon]::LogonUser($name,$env:COMPUTERNAME,$password,2,0,[ref]$token)) {
 throw 'windows_console_credential_rejected: import the existing local Windows lab account password and rerun provisioning'
}
$null=[YokeConsoleLogon]::CloseHandle($token)
"""


RETURN_TO_CONSOLE = r"""
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class YokeConsole {
 [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId();
 [DllImport("wtsapi32.dll",SetLastError=true)]
 static extern bool WTSQuerySessionInformationW(IntPtr server,uint session,int info,out IntPtr value,out uint size);
 [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr value);
 public static object Query(uint session,int info) {
  IntPtr value; uint size;
  if(!WTSQuerySessionInformationW(IntPtr.Zero,session,info,out value,out size))
    throw new Win32Exception();
  try { return info==8 ? (object)Marshal.ReadInt32(value) : Marshal.PtrToStringUni(value); }
  finally { WTSFreeMemory(value); }
 }
}
'@
$console=[YokeConsole]::WTSGetActiveConsoleSessionId()
if ($console -eq [uint32]::MaxValue) {
 throw 'windows_console_detached: inspect the VM console and rerun provisioning'
}
$processes=Get-CimInstance Win32_Process -Filter "Name='explorer.exe' AND SessionId>0"
$owned=@($processes | Where-Object { (Invoke-CimMethod -InputObject $_ -MethodName GetOwnerSid).Sid -eq $sid } |
 Select-Object -ExpandProperty SessionId -Unique)
if ($console -in $owned) { exit 0 }
if ([YokeConsole]::Query($console,5)) {
 throw 'windows_console_occupied: disconnect the other console user before resuming lab QA'
}
$disconnected=@($owned | Where-Object { [YokeConsole]::Query($_,8) -eq 4 })
# A fast reconnect or sign-out can clear the disconnected session before the task runs.
if (!$disconnected.Count) { exit 0 }
if ($disconnected.Count -ne 1) {
 throw 'windows_console_session_ambiguous: sign out duplicate lab sessions and reboot'
}
& "$env:SystemRoot\System32\tscon.exe" $disconnected[0] /dest:console
if ($LASTEXITCODE) {
 throw "windows_console_return_failed: tscon exited $LASTEXITCODE; inspect Task Scheduler and the VM console"
}
"""


def console_settings_script():
    # Task Scheduler retains a static action restricted to SYSTEM and Administrators.
    # The only embedded input is the local account SID resolved by the administrator.
    return r"""
$sid=(Get-LocalUser -Name $name).SID.Value
$profilePath=(Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid").ProfileImagePath
$hive="Registry::HKEY_USERS\$sid"
$loaded=!(Test-Path $hive)
if ($loaded) {
 & reg.exe load "HKU\$sid" (Join-Path $profilePath 'NTUSER.DAT') | Out-Null
 if ($LASTEXITCODE) { throw 'windows_console_profile_unavailable: repair the lab account profile and retry' }
}
try {
 Set-ItemProperty "$hive\Control Panel\Desktop" -Name ScreenSaveActive -Value '0'
 Set-ItemProperty "$hive\Control Panel\Desktop" -Name ScreenSaverIsSecure -Value '0'
 $policy="$hive\Software\Microsoft\Windows\CurrentVersion\Policies\System"
 if (!(Test-Path -LiteralPath $policy)) { New-Item -Path $policy -Force | Out-Null }
 New-ItemProperty $policy -Name DisableLockWorkstation -PropertyType DWord -Value 1 -Force | Out-Null
} finally {
 if ($loaded) {
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
  & reg.exe unload "HKU\$sid" | Out-Null
  if ($LASTEXITCODE) { throw 'windows_console_profile_unload_failed: unload the lab account hive and rerun' }
 }
}
$program=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('RETURN_PROGRAM'))
$header='$sid='+"'"+$sid+"'"
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(($header+[Environment]::NewLine+$program)))
$scheduler=New-Object -ComObject Schedule.Service
$scheduler.Connect()
$definition=$scheduler.NewTask(0)
$definition.Settings.ExecutionTimeLimit='PT30S'
$definition.Settings.DisallowStartIfOnBatteries=$false
$definition.Settings.StopIfGoingOnBatteries=$false
$definition.Principal.UserId='SYSTEM'
$definition.Principal.LogonType=5
$definition.Principal.RunLevel=1
$trigger=$definition.Triggers.Create(11) # TASK_TRIGGER_SESSION_STATE_CHANGE
$trigger.UserId="$env:COMPUTERNAME\$name"
$trigger.StateChange=4 # TASK_REMOTE_DISCONNECT
$trigger.Delay='PT2S'
$action=$definition.Actions.Create(0)
$action.Path="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$action.Arguments="-NoLogo -NoProfile -NonInteractive -EncodedCommand $encoded"
$action.WorkingDirectory="$env:SystemRoot\System32"
$null=$scheduler.GetFolder('\').RegisterTaskDefinition(
 'YokeQa-ReturnToConsole',$definition,22,'SYSTEM',$null,5,'D:P(A;;GA;;;SY)(A;;GA;;;BA)')
Write-Output 'Yoke Windows console setup ready. Reboot once, then run yoke test-machine verify.'
""".replace(
        "RETURN_PROGRAM", base64.b64encode(RETURN_TO_CONSOLE.encode()).decode("ascii")
    )
