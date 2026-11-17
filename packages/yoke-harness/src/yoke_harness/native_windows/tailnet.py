"""Verify live Tailscale identity before accepting tailnet-only firewall scope."""

SCRIPT = r"""
function Get-YokeTailnetProof {
 $exe=Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
 if(!(Test-Path -LiteralPath $exe -PathType Leaf)){return $null}
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
