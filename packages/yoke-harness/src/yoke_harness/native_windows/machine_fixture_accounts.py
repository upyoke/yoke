"""Idempotent SYSTEM PowerShell for the system proxy with its own root CA and
the second local user.

The prelude (machine_fixtures.PRELUDE) defines ``$testUser``,
``$secondUser``, ``$fixtureRoot``, ``$publicKey`` and the helpers used here.
"""

from yoke_harness.native_windows.profile import HELPERS as PROFILE_HELPERS
from yoke_harness.native_windows.user_ssh import SCRIPT as USER_SSH_SCRIPT

PROXY_ADDRESS = "127.0.0.1:18080"
PROXY_TASK = "YokeQaFixtureProxy"
MITMPROXY_VERSION = "12.1.2"
MITMPROXY_URL = (
    f"https://downloads.mitmproxy.org/{MITMPROXY_VERSION}/"
    f"mitmproxy-{MITMPROXY_VERSION}-windows-x86_64.zip"
)
MITMPROXY_ZIP_SHA256 = "81c268b4d4965899f59043201bd0707075c5b820310be382b2fd41c554f370a2"
MITMDUMP_SHA256 = "fb7596452dfa4e09250298a1711fa67519bc2d7e04a5dc99b95b45385b3b8dcf"
WININET_KEY = r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings"
WININET_POLICY_KEY = (
    r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\CurrentVersion\Internet Settings"
)

PROXY_CA_CENSUS = r"""
function Get-YokeProxyCaResidue {
 foreach($store in @('Root','CA')){
  foreach($candidate in Get-ChildItem -LiteralPath ('Cert:\LocalMachine\'+$store)){
   # Decode attributes independently; the provider can display them in either order.
   $attributes=$candidate.SubjectName.Decode([Security.Cryptography.X509Certificates.X500DistinguishedNameFlags]::UseNewLines) -split '\r?\n'
   if(($attributes -match '^\s*CN\s*=\s*(mitmproxy|"mitmproxy")\s*$') -and
      ($attributes -match '^\s*O\s*=\s*(mitmproxy|"mitmproxy")\s*$')){
    [ordered]@{store=$store;thumbprint=$candidate.Thumbprint}
   }
  }
 }
}
"""

_PROXY_VALUES = f"""$proxyAddress='{PROXY_ADDRESS}'; $proxyTask='{PROXY_TASK}'
$wininet='{WININET_KEY}'; $wininetPolicy='{WININET_POLICY_KEY}'
$exe=Join-Path $fixtureRoot 'mitmdump.exe'; $conf=Join-Path $fixtureRoot 'conf'
$cer=Join-Path $conf 'mitmproxy-ca-cert.cer'
function Test-YokeProxyListening {{
 @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
  Where-Object {{$_.Port -eq {PROXY_ADDRESS.rsplit(':', 1)[1]}}}).Count -gt 0
}}
function Test-YokeWinHttpDirect {{((& netsh.exe winhttp show proxy) -join ' ') -match 'Direct access'}}
"""

PROXY_SETUP = (
    _PROXY_VALUES
    + f"""
New-Item -ItemType Directory -Force $fixtureRoot | Out-Null
# Users read the fixture binaries; the CA key folder stays SYSTEM-only.
& icacls.exe $fixtureRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
if($LASTEXITCODE){{throw 'proxy_fixture_acl_failed: inspect the fixture folder ACL'}}
if(!(Test-Path -LiteralPath $exe) -or (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne '{MITMDUMP_SHA256}'){{
 $zip=Join-Path $env:TEMP ('yoke-mitmproxy-'+[Guid]::NewGuid().ToString('N')+'.zip')
 try {{
  Invoke-WebRequest -UseBasicParsing '{MITMPROXY_URL}' -OutFile $zip
  if((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne '{MITMPROXY_ZIP_SHA256}'){{throw 'proxy_fixture_download_mismatch: the mitmproxy release does not match its pinned SHA-256'}}
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive=[IO.Compression.ZipFile]::OpenRead($zip)
  try {{[IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry('mitmdump.exe'),$exe,$true)}} finally {{$archive.Dispose()}}
 }} finally {{Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue}}
 if((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne '{MITMDUMP_SHA256}'){{throw 'proxy_fixture_binary_mismatch: mitmdump.exe does not match its pinned SHA-256'}}
}}
New-Item -ItemType Directory -Force $conf | Out-Null
& icacls.exe $conf /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if($LASTEXITCODE){{throw 'proxy_fixture_acl_failed: inspect the CA folder ACL'}}
if(!(Get-ScheduledTask -TaskName $proxyTask -ErrorAction SilentlyContinue)){{
 $action=New-ScheduledTaskAction -Execute $exe -Argument ('--listen-host 127.0.0.1 --listen-port {PROXY_ADDRESS.rsplit(':', 1)[1]} --set confdir="'+$conf+'"')
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 Register-ScheduledTask -TaskName $proxyTask -Action $action -User 'SYSTEM' -RunLevel Highest -Settings $settings | Out-Null
}}
if((Get-ScheduledTask -TaskName $proxyTask).State -ne 'Running'){{Start-ScheduledTask -TaskName $proxyTask}}
$deadline=[DateTime]::UtcNow.AddSeconds(90)
while(!((Test-Path -LiteralPath $cer) -and (Test-YokeProxyListening))){{
 if([DateTime]::UtcNow -gt $deadline){{throw 'proxy_fixture_not_listening: mitmdump did not listen with its CA within 90s; inspect the YokeQaFixtureProxy task'}}
 Start-Sleep -Milliseconds 500
}}
$cert=[Security.Cryptography.X509Certificates.X509Certificate2]::new($cer)
$trustedCert='Cert:\\LocalMachine\\Root\\'+$cert.Thumbprint
if(!(Test-Path -LiteralPath $trustedCert)){{
 Import-Certificate -FilePath $cer -CertStoreLocation Cert:\\LocalMachine\\Root | Out-Null
}}
if(((& netsh.exe winhttp show proxy) -join ' ') -notmatch [regex]::Escape($proxyAddress)){{
 & netsh.exe winhttp set proxy proxy-server=$proxyAddress bypass-list='<local>' | Out-Null
 if($LASTEXITCODE){{throw 'proxy_fixture_winhttp_failed: inspect netsh winhttp'}}
}}
if(!(Test-Path -LiteralPath $wininetPolicy)){{New-Item -Path $wininetPolicy -Force | Out-Null}}
New-ItemProperty -LiteralPath $wininetPolicy -Name ProxySettingsPerUser -PropertyType DWord -Value 0 -Force | Out-Null
New-ItemProperty -LiteralPath $wininet -Name ProxyEnable -PropertyType DWord -Value 1 -Force | Out-Null
New-ItemProperty -LiteralPath $wininet -Name ProxyServer -PropertyType String -Value $proxyAddress -Force | Out-Null
$verify=[ordered]@{{proxy=$proxyAddress;task=[string](Get-ScheduledTask -TaskName $proxyTask).State;listening=(Test-YokeProxyListening)
 ca_subject=$cert.Subject;ca_thumbprint=$cert.Thumbprint;ca_trusted=(Test-Path -LiteralPath $trustedCert)
 winhttp=(((& netsh.exe winhttp show proxy) -join ' ') -match [regex]::Escape($proxyAddress))
 wininet_machine=((Get-ItemProperty -LiteralPath $wininet).ProxyEnable -eq 1)}}
if($verify.task -ne 'Running' -or !$verify.listening -or !$verify.ca_trusted -or !$verify.winhttp -or !$verify.wininet_machine){{
 throw ('proxy_fixture_not_applied: inspect the proxy task, CA and proxy settings: '+($verify | ConvertTo-Json -Compress))
}}
"""
)

PROXY_UNDO = (
    _PROXY_VALUES
    + PROXY_CA_CENSUS
    + r"""
if(Get-ScheduledTask -TaskName $proxyTask -ErrorAction SilentlyContinue){
 Stop-ScheduledTask -TaskName $proxyTask -ErrorAction SilentlyContinue
 Unregister-ScheduledTask -TaskName $proxyTask -Confirm:$false
}
Get-Process mitmdump -ErrorAction SilentlyContinue | Stop-Process -Force
$deadline=[DateTime]::UtcNow.AddSeconds(30)
while((Get-Process mitmdump -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 500}
if(Test-Path -LiteralPath $cer){
 $cert=[Security.Cryptography.X509Certificates.X509Certificate2]::new($cer)
 foreach($store in @('Root','CA')){
  $ownedCert='Cert:\LocalMachine\'+$store+'\'+$cert.Thumbprint
  if(Test-Path -LiteralPath $ownedCert){Remove-Item -LiteralPath $ownedCert -Force}
  if(Test-Path -LiteralPath $ownedCert){throw "proxy_fixture_owned_ca_retained: inspect $ownedCert and retry; the fixture certificate file was kept"}
 }
}
if(!(Test-YokeWinHttpDirect)){& netsh.exe winhttp reset proxy | Out-Null}
Remove-ItemProperty -LiteralPath $wininetPolicy -Name ProxySettingsPerUser -ErrorAction SilentlyContinue
Remove-ItemProperty -LiteralPath $wininet -Name ProxyEnable,ProxyServer -ErrorAction SilentlyContinue
# The profile restore skips NTUSER.DAT, so the test user's own proxy is reset here.
$userSettings='Registry::HKEY_USERS\'+(Get-YokeUserSid $testUser)+'\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
if(Test-Path -LiteralPath $userSettings){Remove-ItemProperty -LiteralPath $userSettings -Name ProxyEnable,ProxyServer -ErrorAction SilentlyContinue}
if(Test-Path -LiteralPath $fixtureRoot){Remove-Item -LiteralPath $fixtureRoot -Recurse -Force}
$residue=@(Get-YokeProxyCaResidue)
$verify=[ordered]@{task=[bool](Get-ScheduledTask -TaskName $proxyTask -ErrorAction SilentlyContinue)
 process=[bool](Get-Process mitmdump -ErrorAction SilentlyContinue);listening=(Test-YokeProxyListening)
 ca_present=($residue.Count -gt 0);unattributed_ca=$residue
 winhttp_direct=(Test-YokeWinHttpDirect);wininet_machine=($null -ne (Get-ItemProperty -LiteralPath $wininet).ProxyEnable)
 per_user_policy=($null -ne (Get-ItemProperty -LiteralPath $wininetPolicy -ErrorAction SilentlyContinue).ProxySettingsPerUser)
 fixture_root=(Test-Path -LiteralPath $fixtureRoot)}
if($verify.task -or $verify.process -or $verify.listening -or $verify.ca_present -or !$verify.winhttp_direct -or $verify.wininet_machine -or $verify.per_user_policy -or $verify.fixture_root){
 throw ('proxy_fixture_not_undone: inspect the failed state and establish certificate ownership before changing trust: '+($verify | ConvertTo-Json -Compress -Depth 4))
}
"""
)

SECOND_USER_SETUP = (
    PROFILE_HELPERS
    + r"""
$name=$secondUser
$account=Get-LocalUser -Name $name -ErrorAction SilentlyContinue
if(!$account){
 # Key logon and S4U tasks need no password: generate one, set it, keep none.
 $bytes=[byte[]]::new(24); [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
 $secure=ConvertTo-SecureString ([Convert]::ToBase64String($bytes)+'aA1!') -AsPlainText -Force
 $account=New-LocalUser -Name $name -Password $secure -PasswordNeverExpires -AccountNeverExpires
 $secure.Dispose(); $bytes=$null
}
if(!$account.Enabled){Enable-LocalUser -Name $name}
$sid=$account.SID.Value
if((Get-YokeGroupSids 'S-1-5-32-544') -contains $sid){Remove-LocalGroupMember -SID 'S-1-5-32-544' -Member $sid}
if((Get-YokeGroupSids 'S-1-5-32-545') -notcontains $sid){Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $sid}
$homePath=Initialize-YokeProfile $sid $name
New-Item -ItemType Directory -Force "$homePath\.ssh" | Out-Null
USER_SSH_ACCESS
$account=Get-LocalUser -Name $name
$verify=[ordered]@{user=$name;enabled=$account.Enabled;administrator=((Get-YokeGroupSids 'S-1-5-32-544') -contains $sid)
 users=((Get-YokeGroupSids 'S-1-5-32-545') -contains $sid);authorized_key=(Test-Path -LiteralPath "$homePath\.ssh\authorized_keys")}
if(!$verify.enabled -or $verify.administrator -or !$verify.users -or !$verify.authorized_key){throw 'second_user_not_ready: inspect the second local account'}
""".replace("USER_SSH_ACCESS", USER_SSH_SCRIPT.replace("PUBLIC_KEY", "$publicKey"))
)

# Undo keeps the account and its profile: only Yoke and uv leave it.
SECOND_USER_UNDO = (
    PROFILE_HELPERS
    + r"""
$account=Get-LocalUser -Name $secondUser -ErrorAction SilentlyContinue
$homePath=if($account){Resolve-YokeProfile $account.SID.Value}else{$null}
$residue=@()
if($homePath){
 $sid=$account.SID.Value; $bin=Join-Path $homePath '.local\bin'
 $paths=@(@('yoke.cmd','yoke.exe','yoke','uv.exe','uvx.exe','uvw.exe') | ForEach-Object {Join-Path $bin $_}) +
  @(@('AppData\Roaming\uv','AppData\Local\uv') | ForEach-Object {Join-Path $homePath $_})
 foreach($path in $paths){if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path -Recurse -Force}}
 $hive=$sid; $mounted=$false
 if(!(Test-Path -LiteralPath "Registry::HKEY_USERS\$sid")){
  $hive='YokeQaSecondUser'
  & reg.exe load "HKU\$hive" (Join-Path $homePath 'NTUSER.DAT') | Out-Null
  if($LASTEXITCODE){throw 'second_user_hive_unavailable: sign the second user out, then retry'}
  $mounted=$true
 }
 try {
  $environment=[Microsoft.Win32.Registry]::Users.OpenSubKey("$hive\Environment",$true)
  if($environment){
   try {
    $raw=$environment.GetValue('Path',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if($raw){
     $kept=@($raw.Split(';') | Where-Object {$_ -and $_.Replace('%USERPROFILE%',$homePath).TrimEnd('\') -ne $bin})
     if(($kept -join ';') -ne $raw){$environment.SetValue('Path',($kept -join ';'),$environment.GetValueKind('Path'))}
     $raw=$environment.GetValue('Path',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
     if(@($raw.Split(';') | Where-Object {$_.Replace('%USERPROFILE%',$homePath).TrimEnd('\') -eq $bin}).Count){$residue+='PATH'}
    }
   } finally {$environment.Dispose()}
  }
  $python=[Microsoft.Win32.Registry]::Users.OpenSubKey("$hive\Software\Python",$true)
  if($python){
   try {$python.DeleteSubKeyTree('Astral',$false); if($python.OpenSubKey('Astral')){$residue+='uv Python registry'}} finally {$python.Dispose()}
  }
 } finally {
  if($mounted){[GC]::Collect(); [GC]::WaitForPendingFinalizers(); & reg.exe unload "HKU\$hive" | Out-Null}
 }
 $residue+=@($paths | Where-Object {Test-Path -LiteralPath $_})
}
$verify=[ordered]@{user=$secondUser;present=[bool]$account;yoke_absent=!$residue.Count;uv_absent=!$residue.Count}
if($residue.Count){throw ('second_user_residue: Yoke or uv remain in the second profile: '+($residue -join ', '))}
"""
)
