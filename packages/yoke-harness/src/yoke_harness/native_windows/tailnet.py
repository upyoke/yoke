"""Verify live Tailscale identity before accepting tailnet-only firewall scope."""

from yoke_harness.native_windows.receipts import GUARDS

SCRIPT = GUARDS + r"""
function Assert-YokeTailnetPrivate($path,$directory) {
 try {Assert-YokeRecoveryObject $path $directory} catch {
  $problem=$_.Exception.Message; $probeOwner='unavailable'
  try {$probeOwner=(Get-Acl -LiteralPath $path -ErrorAction Stop).GetOwner([Security.Principal.SecurityIdentifier]).Value} catch {}
  throw ($problem+'; probe='+[IO.Path]::GetFileName($path)+'; owner='+$probeOwner)
 }
 $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
 if($path -eq 'C:\ProgramData\YokeQa\private' -and !$acl.AreAccessRulesProtected){throw 'windows_rdp_firewall_failed: provision the protected private probe directory'}
 $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if($rules.Count -ne 2){throw 'windows_rdp_firewall_failed: require private SYSTEM/Administrators probe paths'}
 foreach($rule in $rules){
  if($rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl){throw 'windows_rdp_firewall_failed: untrusted probe permissions'}
 }
}
function Invoke-YokeSystemTailnetProof($exe,$body) {
 # A Windows LocalAPI status request can select the caller's Tailscale profile.
 # Query as SYSTEM, which does not select an OS-user profile; never repair auth.
 $private='C:\ProgramData\YokeQa\private'
 Assert-YokeTailnetPrivate $private $true
 $nonce=[Guid]::NewGuid().ToString('N')
 $probeRoot=Join-Path $private ('TailnetProbe-'+$nonce)
 $taskName='YokeQaTailnetProbe-'+$nonce
 $registered=$null; $instance=$null
 New-Item -ItemType Directory -Path $probeRoot -ErrorAction Stop | Out-Null
 try {
  $acl=Get-Acl -LiteralPath $probeRoot
  $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
  Set-Acl -LiteralPath $probeRoot -AclObject $acl -ErrorAction Stop
  Assert-YokeTailnetPrivate $probeRoot $true
  $scriptPath=Join-Path $probeRoot 'probe.ps1'; $resultPath=Join-Path $probeRoot 'proof.json'
  $payload="`$ErrorActionPreference='Stop'`nfunction Get-YokeTailnetProof {"+$body+"`n}`n"
  $payload+="`$r=@{nonce='$nonce';sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;ok=`$false}`n"
  $payload+="try {`$r.proof=Get-YokeTailnetProof -Executable '"+$exe.Replace("'","''")+"';`$r.ok=`$true} catch {}`n"
  $payload+="[IO.File]::WriteAllText('$resultPath.tmp',(`$r | ConvertTo-Json -Depth 5 -Compress));[IO.File]::Move('$resultPath.tmp','$resultPath')"
  $stream=[IO.File]::Open($scriptPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
   $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($true))
   try {$writer.Write($payload)} finally {$writer.Dispose()}
  } finally {$stream.Dispose()}
  # Only this exclusively created file is ours; never repair a pre-existing owner.
  $acl=Get-Acl -LiteralPath $scriptPath
  $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
  Set-Acl -LiteralPath $scriptPath -AclObject $acl -ErrorAction Stop
  Assert-YokeTailnetPrivate $scriptPath $false
  $scheduler=New-Object -ComObject Schedule.Service; $scheduler.Connect()
  $folder=$scheduler.GetFolder('\'); $definition=$scheduler.NewTask(0)
  $definition.Principal.UserId='S-1-5-18'; $definition.Principal.LogonType=5; $definition.Principal.RunLevel=1
  $definition.Settings.ExecutionTimeLimit='PT15S'; $definition.Settings.AllowDemandStart=$true
  $definition.Settings.DisallowStartIfOnBatteries=$false; $definition.Settings.StopIfGoingOnBatteries=$false
  $action=$definition.Actions.Create(0); $action.Path=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $action.Arguments='-NoProfile -NonInteractive -File "'+$scriptPath+'"'
  $registered=$folder.RegisterTaskDefinition($taskName,$definition,2,'SYSTEM',$null,5,'D:P(A;;GA;;;SY)(A;;GA;;;BA)')
  $instance=$registered.Run($null)
  $deadline=[DateTime]::UtcNow.AddSeconds(20)
  while(!(Test-Path -LiteralPath $resultPath) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 100}
  if(!(Test-Path -LiteralPath $resultPath)){throw 'windows_rdp_firewall_failed: SYSTEM tailnet probe timed out'}
  Assert-YokeTailnetPrivate $resultPath $false
  $result=[IO.File]::ReadAllText($resultPath) | ConvertFrom-Json -ErrorAction Stop
  if($result.nonce -cne $nonce -or $result.sid -cne 'S-1-5-18' -or $result.ok -isnot [bool] -or !$result.ok -or !$result.proof){throw 'windows_rdp_firewall_failed: SYSTEM tailnet identity and adapter proof unavailable'}
  return $result.proof
 } finally {
  if($registered){
   if($registered.State -in @(2,4)){
    if($instance){$instance.Stop()}else{$registered.Stop(0)}
   }
   $cleanupDeadline=[DateTime]::UtcNow.AddSeconds(2)
   while($registered.State -in @(2,4) -and [DateTime]::UtcNow -lt $cleanupDeadline){Start-Sleep -Milliseconds 50}
   if($registered.State -in @(2,4)){throw 'windows_rdp_firewall_failed: owned SYSTEM probe did not stop; preserve its task and files'}
   $folder.DeleteTask($taskName,0)
  }
  Assert-YokeTailnetPrivate $probeRoot $true
  Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction Stop
 }
}
function Get-YokeTailnetProof {
 param([string]$Executable=(Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'))
 $exe=$Executable
 if(!(Test-Path -LiteralPath $exe -PathType Leaf)){return $null}
 if([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18'){
  return Invoke-YokeSystemTailnetProof $exe (${function:Get-YokeTailnetProof}.ToString())
 }
 try {
 $raw=& $exe status --json 2>&1
 if($LASTEXITCODE -ne 0){throw 'windows_rdp_firewall_failed: verify Tailscale status before accepting tailnet RDP'}
 $status=($raw -join "`n") | ConvertFrom-Json -ErrorAction Stop
 if($status.BackendState -ne 'Running' -or !@($status.Self.TailscaleIPs).Count){throw 'windows_rdp_firewall_failed: require a running Tailscale self identity'}
 $addresses=@(); $aliases=@()
 $adapters=@(Get-NetAdapter -IncludeHidden -ErrorAction Stop)
 foreach($value in @($status.Self.TailscaleIPs)){
  $ip=[Net.IPAddress]::Parse([string]$value).ToString()
  if($ip -in @('0.0.0.0','::') -or [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($ip))){throw 'windows_rdp_firewall_failed: invalid Tailscale self address'}
  $rows=@(Get-NetIPAddress -IPAddress $ip -ErrorAction Stop)
  if($rows.Count -ne 1 -or $rows[0].AddressState -ne 'Preferred'){throw 'windows_rdp_firewall_failed: require one live assignment per Tailscale self address'}
  $adapter=@($adapters | Where-Object {$_.ifIndex -eq $rows[0].InterfaceIndex -and $_.Status -eq 'Up'})
  if($adapter.Count -ne 1 -or !$adapter[0].Name){throw 'windows_rdp_firewall_failed: Tailscale adapter assignment is unavailable or ambiguous'}
  $addresses+=$ip; $aliases+=$adapter[0].Name
 }
 return @{addresses=@($addresses | Sort-Object -Unique);aliases=@($aliases | Sort-Object -Unique)}
 }catch {throw 'windows_rdp_firewall_failed: Tailscale self addresses and live adapter assignments are not verified; inspect Tailscale status and network adapters before accepting RDP'}
}
function Test-YokeTailnetOnly($address,$interface,$proof) {
 if(!$proof){return $false}
 $interfaces=@($interface.InterfaceAlias)
 $interfaceOnly=$interfaces.Count -gt 0
 foreach($alias in $interfaces){
  if(!$alias -or $alias -match '[*?]' -or $alias -notin $proof.aliases){$interfaceOnly=$false}
 }
 if($interfaceOnly){return $true}
 $addresses=@($address.LocalAddress)
 if(!$addresses.Count){return $false}
 foreach($value in $addresses){
  $ip=$null
  if(![Net.IPAddress]::TryParse([string]$value,[ref]$ip) -or $ip.ToString() -notin $proof.addresses){return $false}
 }
 return $true
}
"""
