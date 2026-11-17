"""Authorize the standard user without widening sshd policy or directory ACLs."""

SCRIPT = r"""
function Invoke-YokeAcl {
 & icacls.exe @args | Out-Null
 if($LASTEXITCODE){throw ('windows_native_acl_failed: inspect '+$args[0])}
}
$sid=(Get-LocalUser -Name $name -ErrorAction Stop).SID.Value
$sshGroup=Get-LocalGroup -Name 'OpenSSH Users' -ErrorAction SilentlyContinue
if($sshGroup){
 if(@(Get-LocalGroupMember -Group $sshGroup.Name -ErrorAction Stop).SID.Value -notcontains $sid){
  Add-LocalGroupMember -Group $sshGroup.Name -Member $name -ErrorAction Stop
 }
 if(@(Get-LocalGroupMember -Group $sshGroup.Name -ErrorAction Stop).SID.Value -notcontains $sid){
  throw 'windows_test_user_ssh_group_failed: inspect OpenSSH Users membership'
 }
}
Set-Content -LiteralPath "$homePath\.ssh\authorized_keys" -Value PUBLIC_KEY -Encoding ascii
# OI/CI grants apply to directories; never remove child inheritance recursively.
Invoke-YokeAcl "$homePath\.ssh" /inheritance:r /grant:r "${name}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
Invoke-YokeAcl "$homePath\.ssh\authorized_keys" /inheritance:r /grant:r "${name}:F" '*S-1-5-18:F' '*S-1-5-32-544:F'
$acl=Get-Acl -LiteralPath "$homePath\.ssh\authorized_keys" -ErrorAction Stop
$trusted=@($sid,'S-1-5-18','S-1-5-32-544')
if($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted){throw 'windows_test_key_owner_failed: inspect authorized_keys owner'}
$rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if($rules.Count -ne 3 -or @($rules | Where-Object {$_.IdentityReference.Value -notin $trusted -or $_.AccessControlType -ne 'Allow' -or $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl}).Count){
 throw 'windows_test_key_acl_failed: require only test user, SYSTEM and Administrators full access'
}
"""
