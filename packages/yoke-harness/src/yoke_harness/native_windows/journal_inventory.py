"""PowerShell inventory comparison and machine-tool recovery."""

INVENTORY = r"""
function Tool-Key($row) {
 ConvertTo-Json -InputObject @(
  ([string]$row.Name).ToUpperInvariant()
  ([string]$row.Version).ToUpperInvariant()
  ([string]$row.ProviderName).ToUpperInvariant()
 ) -Compress
}
function Json-Key($row) { ConvertTo-Json -InputObject $row -Depth 20 -Compress }
function Only($left,$right,[scriptblock]$key) {
 $counts=[Collections.Generic.Dictionary[string,int]]::new([StringComparer]::Ordinal)
 foreach($row in $right){
  $identity=& $key $row
  if($counts.ContainsKey($identity)){$counts[$identity]++}else{$counts[$identity]=1}
 }
 foreach($row in $left){
  $identity=& $key $row
  if($counts.ContainsKey($identity) -and $counts[$identity] -gt 0){$counts[$identity]--}else{$row}
 }
}
function Difference($saved,$current,[scriptblock]$key) {
 $savedOnly=@(Only $saved $current $key)
 $currentOnly=@(Only $current $saved $key)
 [ordered]@{saved_only=$savedOnly;current_only=$currentOnly}
}
function Has-Difference($diff) {
 $diff.saved_only.Count -gt 0 -or $diff.current_only.Count -gt 0
}
function Restore-Tools($saved,$current,$attempts) {
 $changed=Difference $saved $current ${function:Tool-Key}
 if(!(Has-Difference $changed)){return}
 $catalogPath="$root\private\tool-installers.json"
 $catalog=@()
 if(Test-Path -LiteralPath $catalogPath){
  $catalog=@(Get-Content -Raw -LiteralPath $catalogPath | ConvertFrom-Json)
 }
 foreach($tool in $changed.current_only){
  $identity=Tool-Key $tool
  $attempt=[ordered]@{action='uninstall';tool=$tool;status='skipped_unapproved';exit_code=$null}
  $attempts.Add($attempt)
  if(!($catalog | Where-Object {$_.allow_uninstall -eq $true -and (Tool-Key $_) -ceq $identity})){continue}
  if(@($current | Where-Object {(Tool-Key $_) -ceq $identity}).Count -ne 1 -or
     ($saved | Where-Object {(Tool-Key $_) -ceq $identity})){
   $attempt.status='skipped_ambiguous'
   continue
  }
  try {
   $package=@(Machine-Packages | Where-Object {(Tool-Key $_) -ceq $identity})
   if(!$package){$attempt.status='already_absent';continue}
   if($package.Count -ne 1){$attempt.status='skipped_ambiguous';continue}
   $package[0] | Uninstall-Package -Force -ErrorAction Stop | Out-Null
   $attempt.status=if((Tools) | Where-Object {(Tool-Key $_) -ceq $identity}){'ineffective'}else{'removed'}
  } catch {$attempt.status='failed'}
 }
 foreach($tool in $changed.saved_only){
  $identity=Tool-Key $tool
  $installed=@(Tools)
  $attempt=[ordered]@{action='reinstall';tool=$tool;status='skipped_conflict';exit_code=$null}
  $attempts.Add($attempt)
  if(($installed | Where-Object {$_.Name -eq $tool.Name}) -or
     @($saved | Where-Object {(Tool-Key $_) -ceq $identity}).Count -ne 1){continue}
  $installers=@($catalog | Where-Object {(Tool-Key $_) -ceq $identity -and $_.path})
  $attempt.status='installer_unavailable'
  try {
   if($installers.Count -ne 1){continue}
   $installer=$installers[0]
   if((Get-FileHash -LiteralPath $installer.path).Hash -ne $installer.sha256){continue}
   $process=Start-Process -FilePath $installer.path -ArgumentList $installer.arguments -Wait -PassThru
   $attempt.exit_code=$process.ExitCode
   $attempt.status=if($process.ExitCode -in @(0,3010)){'completed'}else{'failed'}
  } catch {$attempt.status='failed'}
 }
}
function Policy-Entries($policy) {
 $xml=[xml]$policy
 # Publish rule identities and hashes only. Policy bodies can contain local paths and accounts.
 foreach($node in $xml.SelectNodes('//*[@Id] | /AppLockerPolicy | /AppLockerPolicy/RuleCollection')){
  $body=$node.OuterXml
  if($node.LocalName -in @('AppLockerPolicy','RuleCollection')){
   $body=($node.Attributes | ForEach-Object {$_.OuterXml}) -join ' '
  }
  [pscustomobject][ordered]@{type=$node.LocalName;collection=[string]$node.Type;
   id=[string]$node.Id;sha256=(Text-Hash $body)}
 }
}
function Text-Hash([string]$text) {
 $hash=[Security.Cryptography.SHA256]::Create()
 try { [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-','') }
 finally {$hash.Dispose()}
}
function Public-Row($row) {
 $safe=[ordered]@{}
 foreach($property in $row.PSObject.Properties){
  $value=$property.Value
  if($value -is [string]){
   $value=$value -replace '[\p{C}]','?'
   $value=$value -replace '(?i)(?:https?://|\b[a-z]:\\|\\\\)\S+','[REDACTED]'
   if($value.Length -gt 120){$value=$value.Substring(0,120)+'...'}
  }
  $safe[$property.Name]=$value
 }
 $safe
}
function Public-Diff($differences) {
 $public=[ordered]@{}
 foreach($field in $differences.Keys){
  $delta=$differences[$field]
  $public[$field]=@{
   saved_only=@($delta.saved_only | Select-Object -First 6 | ForEach-Object {Public-Row $_})
   current_only=@($delta.current_only | Select-Object -First 6 | ForEach-Object {Public-Row $_})
   saved_only_count=$delta.saved_only.Count;current_only_count=$delta.current_only.Count
  }
 }
 $public
}
"""
