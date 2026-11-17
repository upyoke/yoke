"""Bounded deletion of only the disposable Windows fixture's SID profile."""

PROFILE_CLEANUP_SCRIPT = r"""
function Remove-YokeFixtureProfile([string]$sid){
 Write-Output ('NATIVE_FIXTURE_PROFILE_CLEANUP_BEGIN:'+$sid)
 $clock=[Diagnostics.Stopwatch]::StartNew()
 while($true){
  $profile=Get-CimInstance Win32_UserProfile -Filter ("SID='"+$sid+"'") -ErrorAction Stop
  if(!$profile){Write-Output ('NATIVE_FIXTURE_PROFILE_REMOVED:'+$sid); return}
  if($clock.Elapsed.TotalSeconds -ge 30){
   $profile | Select-Object SID,LocalPath,Loaded,refCount | ConvertTo-Json -Compress | Write-Output
   throw ('native_fixture_profile_cleanup_timeout: owned SID '+$sid)
  }
  if(!$profile.Loaded){
   try {$profile | Remove-CimInstance -ErrorAction Stop}
   catch {
    if($_.FullyQualifiedErrorId -notmatch '^HRESULT 0x80070020,'){throw}
   }
  }
  Start-Sleep -Milliseconds 250
 }
}
"""


AUTOLOGON_CLEARED_SCRIPT = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FixtureLsa {
 [StructLayout(LayoutKind.Sequential)] struct Text {public ushort Length,MaximumLength; public IntPtr Buffer;}
 [StructLayout(LayoutKind.Sequential)] struct Attr {public uint Length; public IntPtr Root,ObjectName; public uint Flags; public IntPtr Descriptor,Qos;}
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system,ref Attr attr,uint access,out IntPtr policy);
 [DllImport("advapi32.dll")] static extern uint LsaRetrievePrivateData(IntPtr policy,ref Text key,out IntPtr value);
 [DllImport("advapi32.dll")] static extern uint LsaFreeMemory(IntPtr memory);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
 public static bool Cleared() {
  var attr=new Attr(); attr.Length=(uint)Marshal.SizeOf(attr);
  IntPtr policy; if(LsaOpenPolicy(IntPtr.Zero,ref attr,4,out policy)!=0) throw new Exception("fixture LSA read denied");
  string name="DefaultPassword"; var key=new Text {Length=(ushort)(name.Length*2),MaximumLength=(ushort)((name.Length+1)*2),Buffer=Marshal.StringToHGlobalUni(name)};
  IntPtr value=IntPtr.Zero;
  try {
   uint status=LsaRetrievePrivateData(policy,ref key,out value);
   if(status==0xC0000034u) return true;
   if(status!=0) throw new Exception("fixture LSA read failed");
   return ((Text)Marshal.PtrToStructure(value,typeof(Text))).Length==0;
  } finally {if(value!=IntPtr.Zero) LsaFreeMemory(value); Marshal.FreeHGlobal(key.Buffer); LsaClose(policy);}
 }
}
'@
if(![FixtureLsa]::Cleared()){throw 'owned autologon LSA credential remains'}
if((Get-ItemProperty $winlogon).AutoAdminLogon -ne '0'){throw 'owned autologon remains enabled'}
if(Get-ItemProperty $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue){throw 'plaintext Winlogon password remains'}
Write-Output 'DISPOSABLE_GUEST_AUTOLOGON_AND_LSA_CLEARED'
"""
