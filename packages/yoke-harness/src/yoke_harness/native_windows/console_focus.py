"""Validate the owned console's visible host before sending desktop input."""


HELPERS = r"""
using System;
using System.Text;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class QaConsoleFocus {
 delegate bool Callback(IntPtr window,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr window,StringBuilder text,int length);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool AttachConsole(uint pid);
 [DllImport("kernel32.dll")] static extern bool FreeConsole();
 [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int type);
 [DllImport("kernel32.dll")] static extern bool SetStdHandle(int type,IntPtr value);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool SetConsoleTitleW(string title);
 static Exception Refuse(string detail) {return new Exception("windows_terminal_focus_refused: "+detail);}
 static void ValidateToken(string token) {
  if(token==null || !System.Text.RegularExpressions.Regex.IsMatch(token,"^YokeQa-[0-9a-f]{32}$")) throw Refuse("owned title token invalid");
 }
 static string Owner(uint pid) {
  var process=OpenProcess(0x1000,false,pid); IntPtr token=IntPtr.Zero;
  if(process==IntPtr.Zero) throw Refuse("process owner unavailable");
  try {
   if(!OpenProcessToken(process,8,out token)) throw Refuse("process token unavailable");
   using(var identity=new WindowsIdentity(token)){return identity.User.Value;}
  } finally {if(token!=IntPtr.Zero) CloseHandle(token);CloseHandle(process);}
 }
 static void ValidateProcess(uint pid) {
  using(var current=Process.GetCurrentProcess())
  using(var target=Process.GetProcessById((int)pid))
  using(var identity=WindowsIdentity.GetCurrent()) {
   if(target.SessionId!=current.SessionId || Owner(pid)!=identity.User.Value) throw Refuse("expected user/session differs");
  }
 }
 public static string Title(IntPtr window) {
  var title=new StringBuilder(4096);GetWindowTextW(window,title,title.Capacity);return title.ToString();
 }
 public static void PrepareTitle(uint pid,string token) {
  ValidateToken(token);
  ValidateProcess(pid);
  var output=GetStdHandle(-11);var input=GetStdHandle(-10);var error=GetStdHandle(-12);
  FreeConsole();
  try {
   if(!AttachConsole(pid)) throw Refuse("owned console attach failed: win32="+Marshal.GetLastWin32Error());
   if(!SetConsoleTitleW(token)) throw Refuse("owned title update failed: win32="+Marshal.GetLastWin32Error());
  } finally {FreeConsole();SetStdHandle(-11,output);SetStdHandle(-10,input);SetStdHandle(-12,error);}
 }
 public static IntPtr Find(uint pid,string token) {
  ValidateToken(token);
  ValidateProcess(pid);
  var matches=new List<IntPtr>();
  EnumWindows((window,parameter)=>{
   if(IsWindowVisible(window) && Title(window).Contains(token)) matches.Add(window);
   return true;
  },IntPtr.Zero);
  if(matches.Count!=1) throw Refuse("owned visible title missing or ambiguous");
  uint owner;GetWindowThreadProcessId(matches[0],out owner);ValidateProcess(owner);
  return matches[0];
 }
 public static void VerifyForeground(uint pid,string token,IntPtr window,string title) {
  if(Find(pid,token)!=window || GetForegroundWindow()!=window || Title(window)!=title) throw Refuse("foreground ownership changed");
 }
}
"""
