"""Resolve a full-HD mode in the Windows fixture's interactive session."""

import base64

from yoke_harness.desktop_geometry import MINIMUM_HEIGHT, MINIMUM_WIDTH

# DEVMODEW's display union includes position, orientation and fixed output.
# Preserve the enumerated DEVMODE and restrict the update to width and height.
DEFINITION = r"""
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class YokeDesktopGeometry {
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 struct Mode {
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string device;
  public ushort spec,driver,size,extra;
  public uint fields;
  public int x,y;
  public uint orientation,fixedOutput;
  public short color,duplex,yres,tt,collate;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string form;
  public ushort dpi;
  public uint bpp,width,height,flags,frequency,icmMethod,icmIntent,media,dither,
      reserved1,reserved2,panningWidth,panningHeight;
 }
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]
 static extern bool EnumDisplaySettings(string device,int index,ref Mode mode);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]
 static extern int ChangeDisplaySettings(ref Mode mode,uint flags);

 static Mode EmptyMode() {
  return new Mode { size=(ushort)Marshal.SizeOf(typeof(Mode)) };
 }
 static bool LargeEnough(Mode mode) {
  return mode.width >= MINIMUM_WIDTH && mode.height >= MINIMUM_HEIGHT;
 }
 static Exception Unavailable(string cause) {
  return new Exception("windows_desktop_resolution_unavailable: " + cause
    + "; select a display mode of at least MINIMUM_WIDTHxMINIMUM_HEIGHT in the test console, or configure its virtual display adapter and retry");
 }
 static Mode Current() {
  Mode current=EmptyMode();
  if (!EnumDisplaySettings(null,-1,ref current)) throw Unavailable("cannot read the active display mode");
  return current;
 }
 static string Resolution(Mode mode) { return mode.width+"x"+mode.height; }
 public static string Observe() {
  Mode current=Current();
  if (!LargeEnough(current)) throw Unavailable("the active display is " + Resolution(current));
  return Resolution(current);
 }
 public static string Ensure() {
  Mode current=Current();
  if (!LargeEnough(current)) {
   Mode best=EmptyMode();
   for (int index=0;;index++) {
    Mode available=EmptyMode();
    if (!EnumDisplaySettings(null,index,ref available)) break;
    if (LargeEnough(available) && (best.width==0 ||
        (long)available.width*available.height < (long)best.width*best.height))
     best=available;
   }
   if (best.width==0) throw Unavailable("no full-HD mode for the " + current.width + "x" + current.height + " display");
   best.fields=0x180000; // DM_PELSWIDTH | DM_PELSHEIGHT
   int status=ChangeDisplaySettings(ref best,1); // CDS_UPDATEREGISTRY
   if (status!=0) throw Unavailable("ChangeDisplaySettings returned " + status);
  }
  return Observe();
 }
}
'@
""".replace("MINIMUM_WIDTH", str(MINIMUM_WIDTH)).replace("MINIMUM_HEIGHT", str(MINIMUM_HEIGHT))

ENSURE = DEFINITION + "$null=[YokeDesktopGeometry]::Ensure()\n"


CONSOLE_DISPLAY_TASK = "YokeQa-ConsoleDisplay"


def console_display_task_script():
    """Configure the standard user's display when the VM console becomes active."""
    program = r"""$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class YokeActiveConsole {
 [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId();
}
'@
if ([Diagnostics.Process]::GetCurrentProcess().SessionId -ne [YokeActiveConsole]::WTSGetActiveConsoleSessionId()) {
 exit 0
}
""" + ENSURE
    encoded = base64.b64encode(program.encode("utf-16le")).decode("ascii")
    return r"""
$displayTask=$scheduler.NewTask(0)
$displayTask.Settings.ExecutionTimeLimit='PT30S'
$displayTask.Settings.DisallowStartIfOnBatteries=$false
$displayTask.Settings.StopIfGoingOnBatteries=$false
$displayTask.Principal.UserId=$sid
$displayTask.Principal.LogonType=3 # TASK_LOGON_INTERACTIVE_TOKEN
$displayTask.Principal.RunLevel=0
$logon=$displayTask.Triggers.Create(9) # TASK_TRIGGER_LOGON
$logon.UserId=$sid
$logon.Delay='PT3S'
$consoleConnect=$displayTask.Triggers.Create(11) # TASK_TRIGGER_SESSION_STATE_CHANGE
$consoleConnect.UserId=$sid
$consoleConnect.StateChange=1 # TASK_CONSOLE_CONNECT
$consoleConnect.Delay='PT3S'
$displayAction=$displayTask.Actions.Create(0)
$displayAction.Path="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$displayAction.Arguments="-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand DISPLAY_PROGRAM"
$null=$scheduler.GetFolder('\').RegisterTaskDefinition(
 'DISPLAY_TASK',$displayTask,22,$sid,$null,3,'D:P(A;;GA;;;SY)(A;;GA;;;BA)')
""".replace("DISPLAY_PROGRAM", encoded).replace("DISPLAY_TASK", CONSOLE_DISPLAY_TASK)
