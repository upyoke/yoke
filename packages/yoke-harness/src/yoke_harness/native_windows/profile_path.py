"""Raw user PATH snapshots for native profile goldens."""


HELPERS = r"""
function Read-YokeUserPath($key){
 $exists=$null -ne $key -and $key.GetValueNames() -contains 'Path'
 if(!$exists){return [pscustomobject]@{exists=$false;raw=$null;kind=$null}}
 $raw=$key.GetValue('Path',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
 $kind=$key.GetValueKind('Path').ToString()
 $snapshot=[pscustomobject]@{exists=$true;raw=$raw;kind=$kind}
 Assert-YokeUserPath $snapshot
 return $snapshot
}
function Assert-YokeUserPath($snapshot){
 $invalid='windows_path_snapshot_invalid: recapture a golden with raw user PATH metadata before reset'
 if($null -eq $snapshot){throw $invalid}
 foreach($name in @('exists','raw','kind')){
  if($snapshot.PSObject.Properties.Name -cnotcontains $name){throw $invalid}
 }
 if($snapshot.exists -isnot [bool]){throw $invalid}
 if($snapshot.exists){
  if($snapshot.raw -isnot [string] -or $snapshot.kind -cnotin @('String','ExpandString')){throw $invalid}
 } elseif($null -ne $snapshot.raw -or $null -ne $snapshot.kind){throw $invalid}
}
function Restore-YokeUserPath($key,$snapshot){
 Assert-YokeUserPath $snapshot
 if($snapshot.exists){
  $kind=[Microsoft.Win32.RegistryValueKind][Enum]::Parse([Microsoft.Win32.RegistryValueKind],$snapshot.kind)
  $key.SetValue('Path',$snapshot.raw,$kind)
 } else {$key.DeleteValue('Path',$false)}
 $actual=Read-YokeUserPath $key
 if($actual.exists -ne $snapshot.exists -or $actual.raw -cne $snapshot.raw -or $actual.kind -cne $snapshot.kind){
  throw 'windows_path_restore_failed: repair user registry access and retry reset'
 }
}
"""
