"""Create a real Windows profile by SID without a credentialed child process."""

from yoke_harness.native_windows.transport import quote


# https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createprofile
HELPERS = r"""
function Resolve-YokeProfile([string]$sid){
 $entry=Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$sid) -ErrorAction SilentlyContinue
 if(!$entry){return $null}
 if(!$entry.ProfileImagePath){throw 'windows_profile_path_invalid: missing SID profile directory'}
 $path=[Environment]::ExpandEnvironmentVariables($entry.ProfileImagePath)
 if(![IO.Path]::IsPathRooted($path) -or ![IO.Directory]::Exists($path) -or ![IO.File]::Exists((Join-Path $path 'NTUSER.DAT'))){
  throw 'windows_profile_path_invalid: inspect the SID profile registration and hive; do not overwrite another profile'
 }
 return [IO.Path]::GetFullPath($path)
}
function Invoke-YokeCreateProfile([string]$sid,[string]$name){
 if(-not ('YokeQa.NativeProfile' -as [type])){
  Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace YokeQa {
 public static class NativeProfile {
  [DllImport("userenv.dll", CharSet=CharSet.Unicode, PreserveSig=true, ExactSpelling=true)]
  public static extern int CreateProfile(string sid, string name, StringBuilder path, uint capacity);
 }
}
'@
 }
 $buffer=New-Object Text.StringBuilder 260
 $hr=[YokeQa.NativeProfile]::CreateProfile($sid,$name,$buffer,$buffer.Capacity)
 return [PSCustomObject]@{HResult=$hr;Path=$buffer.ToString()}
}
function Initialize-YokeProfile([string]$sid,[string]$name){
 $existing=Resolve-YokeProfile $sid
 if($existing){return $existing}
 $created=Invoke-YokeCreateProfile $sid $name
 # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS), including a concurrent creator.
 if($created.HResult -ne 0 -and $created.HResult -ne -2147024713){
  throw ('windows_profile_creation_failed: userenv CreateProfile HRESULT 0x{0:X8}; inspect native profile permissions and registration' -f [int]$created.HResult)
 }
 $path=Resolve-YokeProfile $sid
 if(!$path){throw 'windows_profile_registration_missing: inspect the SID profile registration after CreateProfile'}
 if($created.HResult -eq 0 -and ![string]::Equals($path,$created.Path,[StringComparison]::OrdinalIgnoreCase)){
  throw 'windows_profile_path_mismatch: inspect the SID profile registration before writing authorized keys'
 }
 return $path
}
"""

SCRIPT = (
    HELPERS
    + r"""
$account=Get-LocalUser -Name $name -ErrorAction SilentlyContinue
if(!$account){$account=New-LocalUser -Name $name -Password $secure -PasswordNeverExpires}
# Reusing an account never resets its password. Its stored secret must exist.
$homePath=Initialize-YokeProfile $account.SID.Value $name
"""
)


def missing_password_guard(name: str) -> str:
    return (
        "$ErrorActionPreference='Stop'; "
        f"if(Get-LocalUser -Name {quote(name)} -ErrorAction SilentlyContinue){{"
        "throw 'windows_existing_user_secret_required: restore the existing test-account secret without resetting its password'}; "
        "Write-Output 'YOKE_TEST_USER_ABSENT'"
    )
