"""The SYSTEM/Administrators-only directory for private native QA files."""

GUARDS = r"""
function Assert-YokePrivateObject($path,$directory) {
 $entry=Get-Item -LiteralPath $path -Force -ErrorAction Stop
 if($entry.PSIsContainer -ne $directory){throw 'windows_private_path_invalid: preserve the unexpected object and repair the private path'}
 $check=$entry
 while($check){
  if($check.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_private_path_link_refused: preserve the linked path and provision an unlinked private directory'}
  $check=if($check.PSIsContainer){$check.Parent}else{$check.Directory}
 }
 $owner=(Get-Acl -LiteralPath $path).GetOwner([Security.Principal.SecurityIdentifier]).Value
 if($owner -notin @('S-1-5-18','S-1-5-32-544')){throw 'windows_private_path_owner_refused: preserve the object and inspect its untrusted owner; do not take ownership'}
}
"""

SETUP = GUARDS + r"""
function Set-YokePrivateAcl($path) {
 Assert-YokePrivateObject $path $true
 $acl=Get-Acl -LiteralPath $path
 $acl.SetAccessRuleProtection($true,$false)
 foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){$acl.RemoveAccessRuleSpecific($rule)}
 $inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
 $principals=@('S-1-5-18','S-1-5-32-544')
 foreach($principal in $principals){
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($principal),[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
 }
 Set-Acl -LiteralPath $path -AclObject $acl -ErrorAction Stop
 Assert-YokePrivateObject $path $true
 $actual=Get-Acl -LiteralPath $path
 $rules=@($actual.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if(!$actual.AreAccessRulesProtected -or $rules.Count -ne $principals.Count){throw 'windows_private_path_acl_failed: require the exact protected private DACL'}
 foreach($rule in $rules){
  if($rule.IdentityReference.Value -notin $principals -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or $rule.InheritanceFlags -ne $inherit -or $rule.PropagationFlags -ne 'None' -or $rule.IsInherited){throw 'windows_private_path_acl_failed: repair the exact private permissions'}
 }
}
$root='C:\ProgramData\YokeQa'
foreach($path in @($root,"$root\private")){
 if(!(Test-Path -LiteralPath $path)){
  Assert-YokePrivateObject (Split-Path -Parent $path) $true
  New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
 }
 Set-YokePrivateAcl $path
}
"""
