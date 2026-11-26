"""Shared standard-user process identity probe for native Windows reset."""

# The SSH test user has no WMI namespace grant. Limited process handles can
# read the owner's token and image without elevation or reading process memory.
PROCESS_IDENTITY = r"""Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public static class YokeResetProcess {
 [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
 [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
 static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);

 [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(
  IntPtr process, int informationClass, IntPtr buffer, int length, out int returned);
 [StructLayout(LayoutKind.Sequential)]
 struct UnicodeString {
  public ushort Length;
  public ushort MaximumLength;
  public IntPtr Buffer;
 }

 static string CommandLine(IntPtr process) {
  // ProcessCommandLineInformation returns a UNICODE_STRING and its inline
  // buffer with the same limited query handle used for image and token checks.
  int size;
  NtQueryInformationProcess(process, 60, IntPtr.Zero, 0, out size);
  int header = Marshal.SizeOf(typeof(UnicodeString));
  if(size < header || size > header + 65536) return null;
  IntPtr buffer = Marshal.AllocHGlobal(size);
  try {
   int returned;
   if(NtQueryInformationProcess(process, 60, buffer, size, out returned)!=0) return null;
   var line = (UnicodeString)Marshal.PtrToStructure(buffer, typeof(UnicodeString));
   long offset = line.Buffer.ToInt64() - buffer.ToInt64();
   if(returned > size || offset < header || offset > returned ||
      line.Length == 0 || line.Length % 2 != 0 || line.Length > returned - offset) return null;
   return Marshal.PtrToStringUni(line.Buffer, line.Length / 2);
  } finally {
   Marshal.FreeHGlobal(buffer);
  }
 }

 public static string OwnedImage(int pid, string owner, string expectedImage) {
  IntPtr process=OpenProcess(0x1000, false, pid); // PROCESS_QUERY_LIMITED_INFORMATION
  if(process==IntPtr.Zero) return null;
  IntPtr token=IntPtr.Zero;
  try {
   if(!OpenProcessToken(process, 8, out token)) return null; // TOKEN_QUERY
   using(var identity=new WindowsIdentity(token)) {
    if(identity.User.Value!=owner) return null;
   }
   var path=new StringBuilder(32768);
   int size=path.Capacity;
   if(!QueryFullProcessImageName(process, 0, path, ref size)) return null;
   string image = path.ToString();
   if(String.IsNullOrEmpty(expectedImage)) return image;
   return String.Equals(image, expectedImage, StringComparison.OrdinalIgnoreCase)
    ? CommandLine(process) : null;
  } finally {
   if(token!=IntPtr.Zero) CloseHandle(token);
   CloseHandle(process);
  }
 }
}
'@
$testSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Get-YokeOwnedExecutable($processId){
 [YokeResetProcess]::OwnedImage($processId, $testSid, $null)
}
function Get-YokeOwnedCommandLine($processId,$image){
 [YokeResetProcess]::OwnedImage($processId, $testSid, $image)
}
if(!(Get-YokeOwnedExecutable $PID)){throw 'Cannot verify ownership of the reset process'}
"""
