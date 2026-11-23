"""Disable the verified vendor tray shortcut while preserving its private backup."""

from yoke_harness.native_windows.private_root import GUARDS

SCRIPT = GUARDS + r"""
function Assert-YokeTailnetStartupPrivate($path,$directory) {
 Assert-YokePrivateObject $path $directory
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if(!$acl.AreAccessRulesProtected -or $rules.Count -ne 2 -or @($rules.IdentityReference.Value|Select-Object -Unique).Count -ne 2){throw 'windows_tailnet_startup_private_invalid: preserve the backup and inspect its permissions'}
 foreach($rule in $rules){
  if($rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl){throw 'windows_tailnet_startup_private_invalid: preserve the backup and inspect its permissions'}
 }
}
function Assert-YokeTailnetStartupInventory($root,$allowed) {
 $shell=New-Object -ComObject WScript.Shell
 foreach($entry in @(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop)){
  if($entry.FullName -ieq $allowed){continue}
  if($entry.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_tailnet_startup_unexpected: preserve the linked startup entry'}
  if($entry.Name -match 'Tailscale'){throw 'windows_tailnet_startup_unexpected: preserve the unrecognized startup entry'}
  if(!$entry.PSIsContainer -and $entry.Extension -ieq '.lnk'){
   $link=$shell.CreateShortcut($entry.FullName)
   if($link.TargetPath -match 'tailscale-ipn' -or $link.Arguments -match 'tailscale-ipn'){throw 'windows_tailnet_startup_unexpected: preserve the renamed tray startup entry'}
  }
 }
}
function Disable-YokeTailnetTrayStartup {
 param(
  [string]$UserHome,[string]$UserSid,
  [string]$StartupRoot='C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup',
  [string]$PrivateRoot='C:\ProgramData\YokeQa\private',
  [string]$Executable=(Join-Path $env:ProgramFiles 'Tailscale\tailscale-ipn.exe')
 )
 # A tray LocalAPI request can select a different Windows-user profile. Keep
 # the SYSTEM service and its state; never select, log out or reauthenticate here.
 foreach($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',("Registry::HKEY_USERS\"+$UserSid+'\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'))){
  if(Test-Path -LiteralPath $key){
   $entry=Get-Item -LiteralPath $key -ErrorAction Stop
   foreach($name in $entry.GetValueNames()){
    $value=$entry.GetValue($name)
    if($name -match 'Tailscale' -or ($value -is [string] -and $value -match 'tailscale-ipn')){throw 'windows_tailnet_startup_unexpected: preserve the unrecognized Run entry and inspect it'}
   }
  }
 }
 if($UserHome){
  $userStartup=Join-Path $UserHome 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup'
  if(Test-Path -LiteralPath $userStartup){
   $folder=Get-Item -LiteralPath $userStartup -Force -ErrorAction Stop
   $check=$folder
   while($check){if($check.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_tailnet_startup_unexpected: preserve the linked user startup path'};$check=$check.Parent}
   if(!$folder.PSIsContainer){throw 'windows_tailnet_startup_unexpected: preserve the unrecognized user startup entry'}
   Assert-YokeTailnetStartupInventory $userStartup ''
  }
 }
 if(!(Test-Path -LiteralPath $StartupRoot)){return @{trayStartup='absent'}}
 Assert-YokePrivateObject $StartupRoot $true
 $path=Join-Path $StartupRoot 'Tailscale.lnk'
 Assert-YokeTailnetStartupInventory $StartupRoot $path
 if(!(Test-Path -LiteralPath $path)){return @{trayStartup='absent'}}
 Assert-YokePrivateObject $path $false
 Assert-YokePrivateObject $Executable $false
 if((Get-AuthenticodeSignature -LiteralPath $Executable -ErrorAction Stop).Status -ne 'Valid'){throw 'windows_tailnet_startup_target_invalid: preserve the shortcut; require the signed installed tray executable'}
 $shell=New-Object -ComObject WScript.Shell
 $shortcut=$shell.CreateShortcut($path)
 if($shortcut.TargetPath -ine $Executable -or [string]$shortcut.Arguments -cne ''){throw 'windows_tailnet_startup_target_invalid: preserve the shortcut with unexpected target or arguments'}
 Assert-YokeTailnetStartupPrivate $PrivateRoot $true
 $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
 $length=(Get-Item -LiteralPath $path -Force).Length
 $backup=Join-Path $PrivateRoot ('TailnetTrayStartup-'+$hash+'.lnk.disabled')
 if(!(Test-Path -LiteralPath $backup)){
  $source=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  try {
   $destination=[IO.File]::Open($backup,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
   try {$source.CopyTo($destination)} finally {$destination.Dispose()}
  } finally {$source.Dispose()}
  # Only the exclusively created backup gets its owner/DACL set. Existing
  # collisions are inspected unchanged; no take-ownership recovery.
  $acl=Get-Acl -LiteralPath $backup
  $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
  $acl.SetAccessRuleProtection($true,$false)
  foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){$acl.RemoveAccessRuleSpecific($rule)}
  foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
  Set-Acl -LiteralPath $backup -AclObject $acl -ErrorAction Stop
 }
 Assert-YokeTailnetStartupPrivate $backup $false
 if((Get-Item -LiteralPath $backup -Force).Length -ne $length -or (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash){throw 'windows_tailnet_startup_backup_invalid: preserve both objects; backup differs'}
 Assert-YokePrivateObject $path $false
 if((Get-Item -LiteralPath $path -Force).Length -ne $length -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash){throw 'windows_tailnet_startup_changed: preserve both objects; startup entry changed during backup'}
 Remove-Item -LiteralPath $path -Force -ErrorAction Stop
 if(Test-Path -LiteralPath $path){throw 'windows_tailnet_startup_cleanup_failed: verified shortcut remains in Startup'}
 return @{trayStartup='disabled';backup=$backup;sha256=$hash}
}
"""
