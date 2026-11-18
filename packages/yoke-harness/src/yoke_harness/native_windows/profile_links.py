"""Remove links a profile reset strands, and prove uv kept no managed Python.

Robocopy's /XJ never copies or purges a link, so a mirror keeps a link the
golden lacks while purging the directory it points to. uv's minor-version
Python junction is one: left dangling, the next install fails with uv exit 2.
"""

import json
from pathlib import PureWindowsPath

from yoke_harness.native_windows.transport import quote

REMOVED_MARKER = "YOKE_RESET_LINKS_REMOVED "
UV_PYTHON = r"AppData\Roaming\uv\python"

_SWEEP = r"""function Get-YokeEntryAttributes([string]$p){
 # Reads the link itself, never its target, so a dangling link still answers.
 try {[IO.File]::GetAttributes($p)} catch [IO.FileNotFoundException],[IO.DirectoryNotFoundException] {$null}
}
function Test-YokeLink($attributes){$null -ne $attributes -and ($attributes -band [IO.FileAttributes]::ReparsePoint)}
function Get-YokeGoldenPath([string]$p){Join-Path $source $p.Substring($target.Length).TrimStart('\')}
$stale=New-Object System.Collections.Generic.List[string]
$pending=New-Object System.Collections.Generic.Stack[string]; $pending.Push($target)
while($pending.Count){
 $dir=$pending.Pop()
 try {$entries=@([IO.DirectoryInfo]::new($dir).GetFileSystemInfos())}
 catch {throw ('windows_reset_link_scan_failed: could not list '+$dir+' ('+$_.Exception.Message+'); repair its access for the test user, then rerun yoke test-machine reset')}
 foreach($entry in $entries){
  if($sweepPreserved -contains $entry.FullName){continue}
  if(Test-YokeLink $entry.Attributes){
   # Windows marks its own profile compatibility junctions System.
   if($entry.Attributes -band [IO.FileAttributes]::System){continue}
   if(Test-YokeLink (Get-YokeEntryAttributes (Get-YokeGoldenPath $entry.FullName))){continue}
   $stale.Add($entry.FullName)
  } elseif($entry -is [IO.DirectoryInfo]){$pending.Push($entry.FullName)}
 }
}
$removed=@(); $left=@()
foreach($link in $stale){
 try {
  # Deleting the link itself never follows it into its target.
  if((Get-YokeEntryAttributes $link) -band [IO.FileAttributes]::Directory){[IO.Directory]::Delete($link,$false)}else{[IO.File]::Delete($link)}
 } catch {$left+=$link; continue}
 $removed+=$link
 # Robocopy could not purge the directories that held the link; the uv proof
 # below refuses if one of them still holds uv state.
 $parent=Split-Path -Parent $link
 try {
  while($parent.Length -gt $target.Length -and $null -eq (Get-YokeEntryAttributes (Get-YokeGoldenPath $parent)) -and
        @([IO.Directory]::GetFileSystemEntries($parent)).Count -eq 0){
   [IO.Directory]::Delete($parent,$false); $parent=Split-Path -Parent $parent
  }
 } catch {}
}
Write-Output ('YOKE_RESET_LINKS_REMOVED '+(ConvertTo-Json -Compress -InputObject @($removed)))
$uvPython=Join-Path $target 'UV_PYTHON'
$uvLeft=@($left | Where-Object {$_ -like ($uvPython+'\*')})
if($null -eq (Get-YokeEntryAttributes (Get-YokeGoldenPath $uvPython)) -and $null -ne (Get-YokeEntryAttributes $uvPython)){$uvLeft=@($uvPython)+$uvLeft}
if($uvLeft.Count){
 throw ('windows_reset_uv_state_left: uv-managed Python state the golden lacks remains at '+($uvLeft -join ', ')+'. As the signed-in test user, remove it with cmd /c rmdir (which deletes a junction without following it) or Remove-Item for plain files, then rerun yoke test-machine reset')
}
if($left.Count){
 throw ('windows_reset_link_left: links the golden lacks remain at '+($left -join ', ')+'. As the signed-in test user, delete each with cmd /c rmdir (directory link) or del (file link), then rerun yoke test-machine reset')
}
"""


def stale_link_sweep_script(home, preserved):
    """Run after the golden-to-profile mirror, with $source and $target set."""
    skipped = ",".join(quote(str(PureWindowsPath(home) / p)) for p in preserved)
    return f"$sweepPreserved=@({skipped})\n" + _SWEEP.replace("UV_PYTHON", UV_PYTHON)


def removed_links(stdout):
    """Read the sweep's removal record from the reset's standard output."""
    for line in (stdout or "").splitlines():
        if line.startswith(REMOVED_MARKER):
            return json.loads(line[len(REMOVED_MARKER):])
    return []
