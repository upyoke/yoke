"""C# helper that lists, focuses and drives any top-level window on the desktop.

Compiled by Windows PowerShell 5.1 ``Add-Type`` (C# 5: no interpolation, no
``?.``). Every refusal is an exception whose message starts with its code.
"""

HELPER = r"""
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Automation;
public static class QaDesktop {
 delegate bool Callback(IntPtr window,IntPtr parameter);
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int L,T,R,B; }
 [StructLayout(LayoutKind.Sequential)] public struct Point { public int X,Y; }
 [StructLayout(LayoutKind.Sequential)] struct MouseInput { public int dx,dy; public uint data,flags,time; public IntPtr extra; }
 [StructLayout(LayoutKind.Sequential)] struct KeyInput { public ushort vk,scan; public uint flags,time; public IntPtr extra; }
 [StructLayout(LayoutKind.Explicit)] struct Union { [FieldOffset(0)] public MouseInput mouse; [FieldOffset(0)] public KeyInput key; }
 [StructLayout(LayoutKind.Sequential)] struct Input { public uint type; public Union u; }
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
 [DllImport("user32.dll")] static extern bool IsWindow(IntPtr window);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr window,StringBuilder text,int length);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
 [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr window);
 [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window,int command);
 [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window,out Rect rect);
 [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window,uint flags);
 [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
 [DllImport("user32.dll")] static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from,uint to,bool attach);
 [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint count,Input[] inputs,int size);
 [DllImport("user32.dll")] static extern short VkKeyScanW(char c);
 [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
 [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desktop);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool GetUserObjectInformationW(IntPtr handle,int index,StringBuilder info,int length,out int needed);
 [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
 [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr window,int attribute,out int value,int size);

 static Exception Fail(string code,string detail){return new Exception(code+": "+detail);}
 const string LockedFix="unlock the auto-logged-on test user's console (reboot the lab so autologon signs in, or a person unlocks it over the private RDP route), then retry";

 public static void RequireUnlocked() {
  SetProcessDPIAware();
  IntPtr desktop=OpenInputDesktop(0,false,0x0001);
  if(desktop==IntPtr.Zero) throw Fail("windows_desktop_locked","the input desktop is not readable (win32="+Marshal.GetLastWin32Error()+"); "+LockedFix);
  try {
   var name=new StringBuilder(256); int needed;
   GetUserObjectInformationW(desktop,2,name,512,out needed);
   if(!string.Equals(name.ToString(),"Default",StringComparison.OrdinalIgnoreCase)) throw Fail("windows_desktop_locked","the input desktop is "+name+", not Default; "+LockedFix);
  } finally {CloseDesktop(desktop);}
  int session=Process.GetCurrentProcess().SessionId;
  foreach(var p in Process.GetProcessesByName("LogonUI")) if(p.SessionId==session) throw Fail("windows_desktop_locked","the lock screen is showing; "+LockedFix);
 }
 static string Title(IntPtr window){var text=new StringBuilder(1024);GetWindowTextW(window,text,text.Capacity);return text.ToString();}
 static bool Cloaked(IntPtr window){int value;return DwmGetWindowAttribute(window,14,out value,4)==0&&value!=0;}
 static string ProcessName(uint pid){try{using(var p=Process.GetProcessById((int)pid)){return p.ProcessName;}}catch(ArgumentException){return "";}}
 static Hashtable Describe(IntPtr window) {
  uint pid;GetWindowThreadProcessId(window,out pid);Rect r;GetWindowRect(window,out r);
  var row=new Hashtable();
  row["handle"]="0x"+window.ToInt64().ToString("x");row["title"]=Title(window);row["process"]=ProcessName(pid);row["pid"]=(long)pid;
  row["bounds"]=Bounds(r.L,r.T,r.R-r.L,r.B-r.T);row["foreground"]=GetForegroundWindow()==window;row["minimized"]=IsIconic(window);
  return row;
 }
 static Hashtable Bounds(double x,double y,double w,double h){var b=new Hashtable();b["x"]=(long)x;b["y"]=(long)y;b["width"]=(long)w;b["height"]=(long)h;return b;}
 static List<IntPtr> TopLevel() {
  var rows=new List<IntPtr>();
  EnumWindows(delegate(IntPtr w,IntPtr p){if(IsWindowVisible(w)&&!Cloaked(w)&&Title(w).Length>0) rows.Add(w);return true;},IntPtr.Zero);
  return rows;
 }
 public static object[] Windows(){RequireUnlocked();var rows=new List<object>();foreach(var w in TopLevel()) rows.Add(Describe(w));return rows.ToArray();}
 static bool Matches(IntPtr w,string title,string process,string handle) {
  if(handle.Length>0 && w.ToInt64()!=Convert.ToInt64(handle.StartsWith("0x")?handle.Substring(2):handle,16)) return false;
  if(title.Length>0 && Title(w).IndexOf(title,StringComparison.OrdinalIgnoreCase)<0) return false;
  if(process.Length>0){uint pid;GetWindowThreadProcessId(w,out pid);string name=ProcessName(pid);string want=process.EndsWith(".exe",StringComparison.OrdinalIgnoreCase)?process.Substring(0,process.Length-4):process;if(!string.Equals(name,want,StringComparison.OrdinalIgnoreCase)) return false;}
  return true;
 }
 public static IntPtr Resolve(string title,string process,string handle,int wait) {
  RequireUnlocked();
  var deadline=DateTime.UtcNow.AddSeconds(wait);var matches=new List<IntPtr>();
  while(true){
   matches.Clear();foreach(var w in TopLevel()) if(Matches(w,title,process,handle)) matches.Add(w);
   if(matches.Count>0||DateTime.UtcNow>=deadline) break;
   Thread.Sleep(250);
  }
  if(matches.Count==0) throw Fail("windows_window_not_found","no visible window matches title="+Quote(title)+" process="+Quote(process)+" handle="+Quote(handle)+"; list windows with the `windows` action, launch the app with host-command --gui-session, or raise --wait-seconds");
  if(matches.Count>1){var names=new List<string>();foreach(var w in matches) names.Add(Describe(w)["handle"]+" "+Quote(Title(w)));throw Fail("windows_window_ambiguous",matches.Count+" windows match: "+string.Join(", ",names.ToArray())+"; narrow --title, add --process, or pass --handle");}
  return matches[0];
 }
 static string Quote(string value){return "'"+value+"'";}
 static bool IsForeground(IntPtr window){IntPtr f=GetForegroundWindow();return f==window||GetAncestor(f,3)==window;}
 public static Hashtable Focus(IntPtr window) {
  if(IsIconic(window)) ShowWindow(window,9);
  for(int attempt=0;attempt<3&&!IsForeground(window);attempt++){
   uint ignored;uint target=GetWindowThreadProcessId(GetForegroundWindow(),out ignored);uint self=GetCurrentThreadId();
   bool attached=target!=0&&target!=self&&AttachThreadInput(self,target,true);
   try{
    // A zero-distance mouse move makes this process the last input source,
    // which Windows requires before SetForegroundWindow may take the
    // foreground; unlike an Alt tap it opens no menu bar.
    var nudge=new Input();nudge.type=0;nudge.u.mouse.flags=0x0001;Send(new Input[]{nudge});
    BringWindowToTop(window);SetForegroundWindow(window);
   } finally {if(attached) AttachThreadInput(self,target,false);}
   Thread.Sleep(300);
  }
  if(!IsForeground(window)) throw Fail("windows_foreground_refused","Windows kept "+Quote(Title(GetForegroundWindow()))+" in the foreground instead of "+Quote(Title(window))+"; close the blocking dialog or window shown in a screenshot, then retry");
  return Describe(window);
 }
 static void RequireStillForeground(IntPtr window){if(!IsWindow(window)) throw Fail("windows_window_closed","the target window closed during input; screenshot to see what replaced it");if(!IsForeground(window)) throw Fail("windows_foreground_changed","another window took the foreground during input ("+Quote(Title(GetForegroundWindow()))+"); input may have reached it; screenshot, close that window, then retry");}
 static void Send(Input[] inputs) {
  if(inputs.Length==0) return;
  uint sent=SendInput((uint)inputs.Length,inputs,Marshal.SizeOf(typeof(Input)));
  if(sent!=inputs.Length) throw Fail("windows_input_blocked","Windows accepted "+sent+" of "+inputs.Length+" input events (win32="+Marshal.GetLastWin32Error()+"); the target may run elevated or the desktop locked; run the app as the standard test user and unlock the console");
 }
 static Input Key(ushort vk,char unicode,bool up) {
  var i=new Input();i.type=1;
  if(vk==0){i.u.key.scan=unicode;i.u.key.flags=0x0004;}
  else{i.u.key.vk=vk;if(Extended(vk)) i.u.key.flags|=0x0001;}
  if(up) i.u.key.flags|=0x0002;
  return i;
 }
 static bool Extended(ushort vk){return (vk>=0x21&&vk<=0x2E)||vk==0x5B||vk==0xA3||vk==0xA5;}
 static void Tap(ushort[] chord) {
  var inputs=new List<Input>();
  foreach(var vk in chord) inputs.Add(Key(vk,'\0',false));
  for(int n=chord.Length-1;n>=0;n--) inputs.Add(Key(chord[n],'\0',true));
  Send(inputs.ToArray());
 }
 static ushort Vk(string name) {
  switch(name){
   case "ctrl": case "control": return 0x11; case "shift": return 0x10; case "alt": return 0x12; case "win": case "windows": return 0x5B;
   case "enter": case "return": return 0x0D; case "tab": return 0x09; case "esc": case "escape": return 0x1B; case "space": return 0x20;
   case "backspace": return 0x08; case "delete": case "del": return 0x2E; case "insert": return 0x2D; case "home": return 0x24; case "end": return 0x23;
   case "pageup": return 0x21; case "pagedown": return 0x22; case "left": return 0x25; case "up": return 0x26; case "right": return 0x27; case "down": return 0x28;
  }
  if(name.Length>1&&name[0]=='f'){int n;if(int.TryParse(name.Substring(1),out n)&&n>=1&&n<=24) return (ushort)(0x6F+n);}
  if(name.Length==1){char c=name[0];if(c>='a'&&c<='z') return (ushort)char.ToUpperInvariant(c);if(c>='0'&&c<='9') return (ushort)c;short scan=VkKeyScanW(c);if(scan!=-1) return (ushort)(scan&0xFF);}
  throw Fail("desktop_input_keys_invalid","unknown key "+Quote(name)+"; use names such as ctrl, shift, alt, win, enter, tab, esc, backspace, up, f5 or one character");
 }
 public static Hashtable PressKeys(IntPtr window,string[] chords) {
  var parsed=new List<ushort[]>();
  foreach(var chord in chords){var parts=chord.ToLowerInvariant().Split('+');var keys=new ushort[parts.Length];for(int n=0;n<parts.Length;n++) keys[n]=Vk(parts[n]);parsed.Add(keys);}
  Focus(window);
  foreach(var keys in parsed){Tap(keys);Thread.Sleep(60);RequireStillForeground(window);}
  var row=new Hashtable();row["chords"]=chords;row["window"]=Describe(window);return row;
 }
 public static Hashtable Type(IntPtr window,Hashtable element,string text,int wait) {
  Focus(window);
  if(element.Count>0){var target=Find(window,element,wait);try{target.SetFocus();}catch(InvalidOperationException){Click(window,target);}}
  RequireStillForeground(window);
  for(int start=0;start<text.Length;start+=64){
   var inputs=new List<Input>();
   for(int n=start;n<Math.Min(text.Length,start+64);n++){inputs.Add(Key(0,text[n],false));inputs.Add(Key(0,text[n],true));}
   Send(inputs.ToArray());Thread.Sleep(20);RequireStillForeground(window);
  }
  var row=new Hashtable();row["typed_characters"]=(long)text.Length;row["window"]=Describe(window);return row;
 }
 static AutomationElement Find(IntPtr window,Hashtable want,int wait) {
  var root=AutomationElement.FromHandle(window);var deadline=DateTime.UtcNow.AddSeconds(wait);var found=new List<AutomationElement>();var near=new List<string>();
  while(true){
   found.Clear();near.Clear();
   foreach(AutomationElement e in root.FindAll(TreeScope.Descendants,Condition.TrueCondition)){
    AutomationElement.AutomationElementInformation info;
    try{info=e.Current;}catch(ElementNotAvailableException){continue;}
    string type=info.ControlType.ProgrammaticName.Replace("ControlType.","");
    string label=info.Name??"";
    bool name=!want.ContainsKey("name")||string.Equals(label,(string)want["name"],StringComparison.OrdinalIgnoreCase);
    bool id=!want.ContainsKey("automation_id")||(info.AutomationId??"")==(string)want["automation_id"];
    bool kind=!want.ContainsKey("control_type")||string.Equals(type,(string)want["control_type"],StringComparison.OrdinalIgnoreCase);
    if(name&&id&&kind) found.Add(e);
    else if(want.ContainsKey("name")&&near.Count<10&&label.IndexOf((string)want["name"],StringComparison.OrdinalIgnoreCase)>=0) near.Add(type+" "+Quote(label));
   }
   if(found.Count>0||DateTime.UtcNow>=deadline) break;
   Thread.Sleep(500);
  }
  if(found.Count==0) throw Fail("windows_element_not_found","no element matches "+Selector(want)+(near.Count>0?"; partial name matches: "+string.Join(", ",near.ToArray()):"")+"; read the window in a screenshot, correct the selector, or raise --wait-seconds");
  if(found.Count>1){var rows=new List<string>();foreach(var e in found){if(rows.Count==10) break;rows.Add(e.Current.ControlType.ProgrammaticName.Replace("ControlType.","")+" id="+Quote(e.Current.AutomationId));}throw Fail("windows_element_ambiguous",found.Count+" elements match "+Selector(want)+": "+string.Join(", ",rows.ToArray())+"; add --automation-id or --control-type");}
  return found[0];
 }
 static string Selector(Hashtable want){var parts=new List<string>();foreach(DictionaryEntry e in want) parts.Add(e.Key+"="+Quote((string)e.Value));return string.Join(" ",parts.ToArray());}
 static Hashtable ElementRow(AutomationElement e) {
  var info=e.Current;var r=info.BoundingRectangle;var row=new Hashtable();
  row["name"]=info.Name;row["automation_id"]=info.AutomationId;row["control_type"]=info.ControlType.ProgrammaticName.Replace("ControlType.","");
  row["enabled"]=info.IsEnabled;row["focused"]=info.HasKeyboardFocus;row["offscreen"]=info.IsOffscreen;
  row["bounds"]=r.IsEmpty?null:Bounds(r.X,r.Y,r.Width,r.Height);
  return row;
 }
 static Hashtable Click(IntPtr window,AutomationElement e) {
  System.Windows.Point point;
  if(!e.TryGetClickablePoint(out point)){var r=e.Current.BoundingRectangle;if(r.IsEmpty||e.Current.IsOffscreen) throw Fail("windows_element_not_clickable","the element has no on-screen point; scroll it into view, then retry");point=new System.Windows.Point(r.X+r.Width/2,r.Y+r.Height/2);}
  ClickScreen(window,(int)point.X,(int)point.Y,"left",false);
  return ElementRow(e);
 }
 static void ClickScreen(IntPtr window,int x,int y,string button,bool twice) {
  var p=new Point();p.X=x;p.Y=y;IntPtr hit=GetAncestor(WindowFromPoint(p),2);
  if(hit!=window&&GetAncestor(hit,3)!=window) throw Fail("windows_click_target_obscured","the point ("+x+","+y+") lands on "+Quote(Title(hit))+", not the target window; close or move the covering window, then retry");
  if(!SetCursorPos(x,y)) throw Fail("windows_input_blocked","the cursor could not move; unlock the console and retry");
  uint down=button=="right"?0x0008u:0x0002u;uint up=button=="right"?0x0010u:0x0004u;var inputs=new List<Input>();
  for(int n=0;n<(twice?2:1);n++) foreach(var flag in new uint[]{down,up}){var i=new Input();i.type=0;i.u.mouse.flags=flag;inputs.Add(i);}
  Send(inputs.ToArray());Thread.Sleep(100);
 }
 public static Hashtable ClickAt(IntPtr window,int x,int y,string button,bool twice) {
  Focus(window);Rect r;GetWindowRect(window,out r);
  if(x>=r.R-r.L||y>=r.B-r.T) throw Fail("windows_click_outside_window","("+x+","+y+") is outside the "+(r.R-r.L)+"x"+(r.B-r.T)+" window; measure from the window's top-left corner");
  ClickScreen(window,r.L+x,r.T+y,button,twice);
  var row=new Hashtable();row["screen_point"]=Bounds(r.L+x,r.T+y,0,0);row["window"]=Describe(window);return row;
 }
 public static Hashtable ClickElement(IntPtr window,Hashtable want,string button,bool twice,int wait) {
  Focus(window);var e=Find(window,want,wait);var row=ElementRow(e);
  if(button!="left"||twice){var r=e.Current.BoundingRectangle;ClickScreen(window,(int)(r.X+r.Width/2),(int)(r.Y+r.Height/2),button,twice);} else Click(window,e);
  var result=new Hashtable();result["element"]=row;result["window"]=Describe(window);return result;
 }
 public static Hashtable Read(IntPtr window,Hashtable want,int wait) {
  var e=Find(window,want,wait);var row=ElementRow(e);object pattern;
  if(e.TryGetCurrentPattern(ValuePattern.Pattern,out pattern)) row["value"]=((ValuePattern)pattern).Current.Value;
  if(e.TryGetCurrentPattern(TextPattern.Pattern,out pattern)) row["text"]=((TextPattern)pattern).DocumentRange.GetText(65536);
  var result=new Hashtable();result["element"]=row;result["window"]=Describe(window);return result;
 }
}
"""

__all__ = ["HELPER"]
