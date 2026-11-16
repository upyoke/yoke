"""Provision the dedicated lab desktop's autologon password in LSA, never argv."""

SCRIPT = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class QaAutologon {
 [StructLayout(LayoutKind.Sequential)] struct Text {
  public ushort Length,MaximumLength; public IntPtr Buffer;
 }
 [StructLayout(LayoutKind.Sequential)] struct Attributes {
  public uint Length; public IntPtr RootDirectory,ObjectName; public uint Flags;
  public IntPtr SecurityDescriptor,SecurityQualityOfService;
 }
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system,ref Attributes attr,uint access,out IntPtr policy);
 [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr policy,ref Text key,ref Text value);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
 static Text Value(string text) {
  return new Text {Length=(ushort)(text.Length*2),MaximumLength=(ushort)((text.Length+1)*2),Buffer=Marshal.StringToHGlobalUni(text)};
 }
 public static void Save(string password) {
  var attr=new Attributes(); attr.Length=(uint)Marshal.SizeOf(attr);
  IntPtr policy; var status=LsaOpenPolicy(IntPtr.Zero,ref attr,0x20,out policy);
  if(status!=0) throw new Exception("windows_autologon_lsa_open_failed: run provisioning as administrator");
  var key=Value("DefaultPassword"); var value=Value(password);
  try { if(LsaStorePrivateData(policy,ref key,ref value)!=0) throw new Exception("windows_autologon_lsa_write_failed: repair local security policy and rerun provisioning"); }
  finally {Marshal.ZeroFreeGlobalAllocUnicode(value.Buffer); Marshal.FreeHGlobal(key.Buffer); LsaClose(policy);}
 }
}
'@
[QaAutologon]::Save($password)
$winlogon='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
Set-ItemProperty $winlogon -Name AutoAdminLogon -Value '1'
Set-ItemProperty $winlogon -Name DefaultUserName -Value $name
Set-ItemProperty $winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME
Remove-ItemProperty $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
"""
