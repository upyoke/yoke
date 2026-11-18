"""Permit verified tailnet RDP while refusing public network exposure."""

from yoke_harness.native_windows.tailnet import SCRIPT as TAILNET_SCOPE

SCRIPT = TAILNET_SCOPE + r"""
# Windows Firewall rejects both IPv4 and IPv6 loopback address conditions.
Get-NetFirewallRule -Name YokeQaRdpLoopback -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True -DefaultInboundAction Block
$profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
if($profiles.Count -ne 3 -or @($profiles | Where-Object {$_.Enabled -ne 'True' -or $_.DefaultInboundAction -ne 'Block'}).Count){
 throw 'windows_rdp_firewall_failed: require all effective firewall profiles enabled with default inbound block'
}
$tailnetProof=Get-YokeTailnetProof
foreach($legacy in @(Get-NetFirewallRule -Name 'RemoteDesktop-*' -ErrorAction SilentlyContinue | Where-Object {$_.Enabled -eq 'True'})){
 $address=$legacy | Get-NetFirewallAddressFilter -ErrorAction Stop
 $interface=$legacy | Get-NetFirewallInterfaceFilter -ErrorAction Stop
 if(!(Test-YokeTailnetOnly $address $interface $tailnetProof)){$legacy | Disable-NetFirewallRule -ErrorAction Stop}
}
$allows=Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Direction Inbound -Action Allow -ErrorAction Stop
foreach($allow in $allows){
 $port=$allow | Get-NetFirewallPortFilter -ErrorAction Stop
 if($port.Protocol -notin @('TCP','6','UDP','17','Any','256')){continue}
 $rdpPort=$false
 foreach($value in @($port.LocalPort)){
  if($value -eq 'Any' -or $value -eq '3389'){$rdpPort=$true}
  elseif($value -match '^(\d+)-(\d+)$' -and [int]$Matches[1] -le 3389 -and [int]$Matches[2] -ge 3389){$rdpPort=$true}
 }
 if(!$rdpPort){continue}
 $service=$allow | Get-NetFirewallServiceFilter -ErrorAction Stop
 $app=$allow | Get-NetFirewallApplicationFilter -ErrorAction Stop
 if($app.Package -and $app.Package -notin @('Any','*')){continue}
 # Newer Windows rules can constrain app identity by family instead of SID.
 if($allow.PackageFamilyName -and $allow.PackageFamilyName -ne 'Any' -and $allow.PackageFamilyName -notmatch '[*?]'){continue}
 # System denotes a kernel listener, not the svchost-hosted TermService.
 if($service.Service -eq 'TermService' -or ($service.Service -eq 'Any' -and $app.Program -in @('Any','%SystemRoot%\system32\svchost.exe',(Join-Path $env:WINDIR 'System32\svchost.exe')))){
  $address=$allow | Get-NetFirewallAddressFilter -ErrorAction Stop
  $interface=$allow | Get-NetFirewallInterfaceFilter -ErrorAction Stop
  if(Test-YokeTailnetOnly $address $interface $tailnetProof){continue}
  throw ('windows_rdp_firewall_failed: inspect RDP-capable inbound allow rule '+$allow.Name+'; local='+($address.LocalAddress -join ',')+'; interface='+($interface.InterfaceAlias -join ',')+'; require verified tailnet confinement, never public RDP')
 }
}
Start-Service TermService -ErrorAction Stop
Write-Output 'Native RDP public firewall blocked; verified tailnet RDP and local SSH forwarding are permitted.'
"""
