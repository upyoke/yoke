"""Real Windows firewall filters and adapter facts; only Tailscale status is substituted."""

from yoke_harness.native_windows.tailnet import SCRIPT as TAILNET_SCOPE
from yoke_harness.native_windows.firewall import SCRIPT as FIREWALL_SCRIPT


def verify_tailnet_scope(powershell, directory):
    result = powershell(TAILNET_SCOPE + "\n$fullFirewall=@'\n" + FIREWALL_SCRIPT + "\n'@\n" + r'''
$originalProgramFiles=$env:ProgramFiles
$root=Join-Path $env:TEMP ('YokeTailnetFixture-'+[Guid]::NewGuid().ToString('N'))
$rule='YokeFixtureTailnet-'+[Guid]::NewGuid().ToString('N')
$legacyTailnet='RemoteDesktop-'+$rule
$legacyPublic='RemoteDesktop-public-'+$rule
try {
 $folder=Join-Path $root 'Tailscale'
 New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
 $code=@'
using System;
using System.IO;
using System.Reflection;
using System.Security.Principal;
public class YokeTailnetFixture {
 public static int Main(string[] args) {
  if(WindowsIdentity.GetCurrent().User.Value!="S-1-5-18") return 4;
  if(args.Length!=2 || args[0]!="status" || args[1]!="--json") return 2;
  Console.Write(File.ReadAllText(Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"status.json")));
  return 0;
 }
}
'@
 Add-Type -TypeDefinition $code -OutputAssembly (Join-Path $folder 'tailscale.exe') -OutputType ConsoleApplication -ErrorAction Stop
 $env:ProgramFiles=$root
 $adapter=@(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1)[0]
 $ip=@(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Where-Object {$_.AddressState -eq 'Preferred'} | Select-Object -First 1)[0].IPAddress
 if(!$ip){throw 'real live adapter fixture missing'}
 function Write-Status($state,$ips) {
  @{BackendState=$state;Self=@{TailscaleIPs=@($ips)}} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $folder 'status.json')
 }
 function Assert-Unverified {
  $refused=$false
  try {Get-YokeTailnetProof | Out-Null} catch {
   if($_.Exception.Message -notlike '*windows_rdp_firewall_failed:*'){throw}
   $refused=$true
  }
  if(!$refused){throw 'unverified Tailscale identity was accepted'}
 }
 Write-Status 'Running' @($ip)
 $proof=Get-YokeTailnetProof
 if($proof.addresses -notcontains $ip -or $proof.aliases -notcontains $adapter.Name){throw 'live identity/adapter proof missing'}
 foreach($case in @(@{state='Stopped';ips=@($ip)},@{state='Running';ips=@()},@{state='Running';ips=@('127.0.0.1')},@{state='Running';ips=@('192.0.2.17')})){
  Write-Status $case.state $case.ips
  Assert-Unverified
 }
 # The CLI is substituted, but these are real Windows rule/filter objects.
 New-NetFirewallRule -Name $rule -DisplayName 'Tailscale-In' -Direction Inbound -Action Allow -Protocol Any -LocalAddress $ip -Program Any -Service Any | Out-Null
 function Test-RuleScope {
  $r=Get-NetFirewallRule -Name $rule -ErrorAction Stop
  return (Test-YokeTailnetOnly ($r | Get-NetFirewallAddressFilter) ($r | Get-NetFirewallInterfaceFilter) $proof)
 }
 if(!(Test-RuleScope)){throw 'exact verified self address was refused'}
 $r=Get-NetFirewallRule -Name $rule
 $r | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress @($ip,'192.0.2.17')
 if(Test-RuleScope){throw 'mixed public/unverified address was accepted'}
 $r | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress '100.64.0.0/10'
 if(Test-RuleScope){throw 'tailnet-looking range without exact self identity was accepted'}
 $r | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress Any
 if(Test-RuleScope){throw 'unrestricted Tailscale display name was accepted'}
 $r | Get-NetFirewallInterfaceFilter | Set-NetFirewallInterfaceFilter -InterfaceAlias $adapter.Name
 if(!(Test-RuleScope)){throw 'exact verified adapter was refused'}
 $r | Get-NetFirewallInterfaceFilter | Set-NetFirewallInterfaceFilter -InterfaceAlias Any
 if(Test-RuleScope){throw 'unrestricted interface/address was accepted'}
 # Windows cannot persist wildcard aliases; exercise that defensive input directly.
 foreach($alias in @('*',($adapter.Name+'*'),'?')){
  if(Test-YokeTailnetOnly @{LocalAddress='Any'} @{InterfaceAlias=$alias} $proof){throw 'wildcard interface was accepted'}
 }
 if(Test-YokeTailnetOnly @{LocalAddress=$ip} @{InterfaceAlias='Any'} $null){throw 'missing proof was accepted'}
 # Execute the unchanged full classifier with the substituted CLI identity.
 Write-Status 'Running' @($ip)
 $r | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $ip
 $r | Get-NetFirewallInterfaceFilter | Set-NetFirewallInterfaceFilter -InterfaceAlias Any
 New-NetFirewallRule -Name $legacyTailnet -DisplayName 'owned confined desktop fixture' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -LocalAddress $ip | Out-Null
 New-NetFirewallRule -Name $legacyPublic -DisplayName 'owned public desktop fixture' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -LocalAddress Any | Out-Null
 & ([scriptblock]::Create($fullFirewall))
 if((Get-NetFirewallRule -Name $legacyTailnet).Enabled -ne 'True'){throw 'verified tailnet desktop rule was disabled'}
 if((Get-NetFirewallRule -Name $legacyPublic).Enabled -ne 'False'){throw 'public desktop rule remains enabled'}
 if((Get-NetFirewallRule -Name $rule).Enabled -ne 'True'){throw 'foreign tailnet rule was changed'}
 if(@(Get-ChildItem 'C:\ProgramData\YokeQa\private' -Filter 'TailnetProbe-*').Count){throw 'tailnet probe staging remains'}
 if(@(Get-ScheduledTask -TaskName 'YokeQaTailnetProbe-*' -ErrorAction SilentlyContinue).Count){throw 'tailnet probe task remains'}
 'TAILNET_SCOPE_AND_IDENTITY_VERIFIED'
} finally {
 $env:ProgramFiles=$originalProgramFiles
 Get-NetFirewallRule -Name @($rule,$legacyTailnet,$legacyPublic) -ErrorAction SilentlyContinue | Remove-NetFirewallRule
 Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop
}
''', directory)
    assert result.returncode == 0, result.stderr
    assert "TAILNET_SCOPE_AND_IDENTITY_VERIFIED" in result.stdout
