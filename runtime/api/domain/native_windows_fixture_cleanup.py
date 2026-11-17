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
