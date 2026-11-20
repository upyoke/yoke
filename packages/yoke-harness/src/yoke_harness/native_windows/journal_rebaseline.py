"""Administrator-only approval of an inspected machine-tool inventory change."""

REBASELINE = r"""
function Update-ToolBaseline {
 $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
 $principal=[Security.Principal.WindowsPrincipal]::new($identity)
 if(!$identity.IsSystem -and !$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
  throw 'windows_tool_rebaseline_requires_admin: run the protected program as Administrator'
 }
 Assert-YokeRecoveryObject (Split-Path -Parent $journal) $true
 Assert-YokeRecoveryObject $journal $false
 $saved=Get-Content -Raw -LiteralPath $journal | ConvertFrom-Json
 $current=@(Tools)
 $diff=Difference $saved.state.tools $current ${function:Tool-Key}
 if(!(Has-Difference $diff)){throw 'windows_tool_rebaseline_no_difference: retry the normal restore'}
 $fingerprint=Text-Hash (Json-Key @($saved.lease,@($saved.state.tools),$current))
 if($InspectTools){
  if($AcceptToolsFingerprint -or $ApprovalReason){throw 'windows_tool_rebaseline_invalid: inspect without approval arguments'}
  @{fingerprint=$fingerprint;lease=$saved.lease;tools=$diff} | ConvertTo-Json -Depth 8
  return
 }
 if($AcceptToolsFingerprint -cne $fingerprint -or !$ApprovalReason.Trim() -or $ApprovalReason.Length -gt 512){
  throw 'windows_tool_rebaseline_stale_or_unapproved: inspect the current drift and supply its fingerprint and a verification reason'
 }
 $auditId=[Guid]::NewGuid().ToString('N')
 $auditPath="$root\private\tool-rebaseline-$auditId"
 $audit=@{audit_id=$auditId;approved_at_utc=[DateTime]::UtcNow.ToString('o');approved_by_sid=$identity.User.Value;
   lease=$saved.lease;reason=$ApprovalReason;fingerprint=$fingerprint;tools=$diff}
 $audit | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$auditPath.approval.json" -Encoding UTF8
 $saved.state.tools=$current
 $saved | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath "$auditPath.next.json" -Encoding UTF8
 # Replace atomically and retain the original journal beside the approval receipt.
 [IO.File]::Replace("$auditPath.next.json",$journal,"$auditPath.before.json")
 @{audit_id=$auditId;lease=$saved.lease;status='tool_baseline_accepted'} | ConvertTo-Json -Compress
}
"""
