"""Protected SYSTEM recovery evidence, separate from writable requests."""

RECEIPT = r"C:\ProgramData\YokeQa\receipts\receipt.json"

GUARDS = r"""
function Assert-YokeRecoveryObject($path,$directory) {
 $entry=Get-Item -LiteralPath $path -Force -ErrorAction Stop
 if($entry.PSIsContainer -ne $directory){throw 'windows_recovery_path_invalid: preserve the unexpected object and repair the recovery path'}
 $check=$entry
 while($check){
  if($check.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_recovery_link_refused: preserve the linked path and provision an unlinked recovery directory'}
  $check=if($check.PSIsContainer){$check.Parent}else{$check.Directory}
 }
 $owner=(Get-Acl -LiteralPath $path).GetOwner([Security.Principal.SecurityIdentifier]).Value
 if($owner -notin @('S-1-5-18','S-1-5-32-544')){throw 'windows_recovery_owner_refused: preserve the object and inspect its untrusted owner; do not take ownership'}
}
"""

SETUP = GUARDS + r"""
$sid=(Get-LocalUser -Name $name -ErrorAction Stop).SID.Value
function Set-YokeRecoveryAcl($path,$directory,$userRights) {
 Assert-YokeRecoveryObject $path $directory
 $acl=Get-Acl -LiteralPath $path
 $acl.SetAccessRuleProtection($true,$false)
 foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){$acl.RemoveAccessRuleSpecific($rule)}
 $inherit=if($directory){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
 $expected=@{}
 foreach($principal in @('S-1-5-18','S-1-5-32-544',$sid)){
  if($principal -eq $sid -and !$userRights){continue}
  $rights=if($principal -eq $sid){$userRights}else{'FullControl'}
  $rule=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($principal),[Security.AccessControl.FileSystemRights]$rights,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
  $acl.AddAccessRule($rule); $expected[$principal]=$rule.FileSystemRights
 }
 Set-Acl -LiteralPath $path -AclObject $acl -ErrorAction Stop
 Assert-YokeRecoveryObject $path $directory
 $actual=Get-Acl -LiteralPath $path
 $rules=@($actual.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if(!$actual.AreAccessRulesProtected -or $rules.Count -ne $expected.Count){throw 'windows_recovery_acl_failed: require the exact protected recovery DACL'}
 foreach($rule in $rules){
  if(!$expected.ContainsKey($rule.IdentityReference.Value) -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne $expected[$rule.IdentityReference.Value] -or $rule.InheritanceFlags -ne $inherit -or $rule.PropagationFlags -ne 'None' -or $rule.IsInherited){throw 'windows_recovery_acl_failed: repair the exact recovery permissions'}
 }
}
$recoveryRoot='C:\ProgramData\YokeQa'
foreach($row in @(@{path=$recoveryRoot;rights='ReadAndExecute'},@{path="$recoveryRoot\private";rights=$null},@{path="$recoveryRoot\requests";rights='Modify'},@{path="$recoveryRoot\receipts";rights='ReadAndExecute'})){
 if(!(Test-Path -LiteralPath $row.path)){
  Assert-YokeRecoveryObject (Split-Path -Parent $row.path) $true
  New-Item -ItemType Directory -Path $row.path -ErrorAction Stop | Out-Null
 }
 Set-YokeRecoveryAcl $row.path $true $row.rights
}
foreach($path in @("$recoveryRoot\receipts\receipt.json","$recoveryRoot\receipts\receipt.json.tmp","$recoveryRoot\private\machine-settings.ps1")){
 if(Test-Path -LiteralPath $path){
  $rights=if($path.StartsWith("$recoveryRoot\receipts\")){'ReadAndExecute'}else{$null}
  Set-YokeRecoveryAcl $path $false $rights
 }
}
"""

PUBLISH = GUARDS + r"""
function Assert-YokeProofAcl($path,$directory) {
 Assert-YokeRecoveryObject $path $directory
 $acl=Get-Acl -LiteralPath $path
 $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if($rules.Count -ne 3 -or ($directory -and !$acl.AreAccessRulesProtected)){throw 'windows_recovery_receipt_acl_failed: provision the protected proof directory'}
 $full=@($rules | Where-Object {$_.IdentityReference.Value -in @('S-1-5-18','S-1-5-32-544') -and $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl})
 $read=@($rules | Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -and $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights -eq ([Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Synchronize)})
 if($full.Count -ne 2 -or $read.Count -ne 1){throw 'windows_recovery_receipt_acl_failed: only SYSTEM and Administrators may write proof'}
}
function Publish-YokeReceipt($value) {
 Assert-YokeProofAcl 'C:\ProgramData\YokeQa' $true
 Assert-YokeProofAcl (Split-Path -Parent $receipt) $true
 foreach($path in @($receipt,($receipt+'.tmp'))){if(Test-Path -LiteralPath $path){Assert-YokeProofAcl $path $false}}
 $value | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath ($receipt+'.tmp') -Encoding UTF8 -ErrorAction Stop
 Assert-YokeProofAcl ($receipt+'.tmp') $false
 Move-Item -LiteralPath ($receipt+'.tmp') -Destination $receipt -Force -ErrorAction Stop
 Assert-YokeProofAcl $receipt $false
}
"""
