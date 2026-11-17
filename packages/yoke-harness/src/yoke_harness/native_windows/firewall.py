"""Keep network RDP blocked; local SSH forwarding needs no loopback allow rule."""

SCRIPT = r"""
# Windows Firewall rejects both IPv4 and IPv6 loopback address conditions.
Get-NetFirewallRule -Name YokeQaRdpLoopback -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -Name 'RemoteDesktop-*' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True -DefaultInboundAction Block
$profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
if($profiles.Count -ne 3 -or @($profiles | Where-Object {$_.Enabled -ne 'True' -or $_.DefaultInboundAction -ne 'Block'}).Count){
 throw 'windows_rdp_firewall_failed: require all effective firewall profiles enabled with default inbound block'
}
$legacy=@(Get-NetFirewallRule -PolicyStore ActiveStore -ErrorAction Stop | Where-Object {$_.Enabled -eq 'True' -and ($_.Name -like 'RemoteDesktop-*' -or $_.Name -eq 'YokeQaRdpLoopback')})
if($legacy.Count){throw 'windows_rdp_firewall_failed: a network RDP rule remains enabled'}
$allows=Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Direction Inbound -Action Allow -ErrorAction Stop
foreach($allow in $allows){
 $port=$allow | Get-NetFirewallPortFilter -ErrorAction Stop
 if($port.Protocol -notin @('TCP','6','Any','256')){continue}
 $rdpPort=$false
 foreach($value in @($port.LocalPort)){
  if($value -eq 'Any' -or $value -eq '3389'){$rdpPort=$true}
  elseif($value -match '^(\d+)-(\d+)$' -and [int]$Matches[1] -le 3389 -and [int]$Matches[2] -ge 3389){$rdpPort=$true}
 }
 if(!$rdpPort){continue}
 $service=$allow | Get-NetFirewallServiceFilter -ErrorAction Stop
 $app=$allow | Get-NetFirewallApplicationFilter -ErrorAction Stop
 if($app.Package -and $app.Package -ne 'Any'){continue}
 if($service.Service -eq 'TermService' -or ($service.Service -eq 'Any' -and $app.Program -in @('Any','System','%SystemRoot%\system32\svchost.exe',(Join-Path $env:WINDIR 'System32\svchost.exe')))){
  throw ('windows_rdp_firewall_failed: inspect RDP-capable inbound allow rule '+$allow.Name+'; do not widen network access')
 }
}
Start-Service TermService -ErrorAction Stop
Write-Output 'Native RDP network firewall blocked; use SSH forwarding to 127.0.0.1:3389.'
"""
