"""Idempotent SYSTEM PowerShell for the policy fixtures: admin grant, Task
Scheduler restriction and AppLocker.

Each body reads the current state, changes only what differs, and leaves the
state it proves in ``$verify``; the library wrapper prints it as the record.
The prelude (machine_fixtures.PRELUDE) defines ``$testUser``, ``$golden``
and the group helpers these bodies use.
"""

from yoke_harness.native_windows.profile import HELPERS as PROFILE_HELPERS

TASK_POLICY_KEY = r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\Task Scheduler5.0"

GRANT_ADMIN_SETUP = r"""
$sid=Get-YokeUserSid $testUser
if((Get-YokeGroupSids 'S-1-5-32-544') -notcontains $sid){Add-LocalGroupMember -SID 'S-1-5-32-544' -Member $sid}
$verify=[ordered]@{user=$testUser;administrator=((Get-YokeGroupSids 'S-1-5-32-544') -contains $sid)}
if(!$verify.administrator){throw 'grant_admin_not_applied: inspect the Administrators group'}
"""

GRANT_ADMIN_UNDO = r"""
$sid=Get-YokeUserSid $testUser
if((Get-YokeGroupSids 'S-1-5-32-544') -contains $sid){Remove-LocalGroupMember -SID 'S-1-5-32-544' -Member $sid}
$verify=[ordered]@{user=$testUser;administrator=((Get-YokeGroupSids 'S-1-5-32-544') -contains $sid)}
if($verify.administrator){throw 'grant_admin_not_undone: remove the test user from Administrators'}
"""

TASK_SCHEDULER_SETUP = f"""
$key='{TASK_POLICY_KEY}'
if(!(Test-Path -LiteralPath $key)){{New-Item -Path $key -Force | Out-Null}}
if((Get-ItemProperty -LiteralPath $key -Name 'Task Creation' -ErrorAction SilentlyContinue).'Task Creation' -ne 1){{
 New-ItemProperty -LiteralPath $key -Name 'Task Creation' -PropertyType DWord -Value 1 -Force | Out-Null
}}
$verify=[ordered]@{{policy_key=(Test-Path -LiteralPath $key);task_creation_prohibited=((Get-ItemProperty -LiteralPath $key).'Task Creation' -eq 1)}}
if(!$verify.task_creation_prohibited){{throw 'task_scheduler_policy_not_applied: inspect the Task Scheduler5.0 policy key'}}
"""

TASK_SCHEDULER_UNDO = f"""
$key='{TASK_POLICY_KEY}'
if(Test-Path -LiteralPath $key){{Remove-Item -LiteralPath $key -Recurse -Force}}
$verify=[ordered]@{{policy_key=(Test-Path -LiteralPath $key)}}
if($verify.policy_key){{throw 'task_scheduler_policy_not_undone: delete the Task Scheduler5.0 policy key'}}
"""

# Fixed rule ids: the setup compares them to decide whether the policy differs.
ALLOW_EXE = "9e796dae-08dd-4be8-ac35-cadc7e09e6f1"
DENY_PYTHON = "2d644718-8395-40d4-b9fa-6c4a2cbf1724"
ALLOW_SCRIPT = "3b41b92d-e8ff-4470-80a4-cac53ac148de"
DENY_YOKE = "ee70f9bd-8ca7-4d40-80ce-62837120df7a"
ALLOW_APPX = "062dc037-e9a2-44af-8977-c6ecef37b148"
APPLOCKER_RULE_IDS = tuple(
    sorted((ALLOW_EXE, DENY_PYTHON, ALLOW_SCRIPT, DENY_YOKE, ALLOW_APPX))
)

# Deny wins over allow, so only the test user's two targets are blocked; the
# exception keeps the sealed probe interpreter runnable, so a leftover policy
# reaches the probe and fails as probe_machine_drift instead of hiding it.
APPLOCKER_POLICY = f"""<AppLockerPolicy Version="1">
<RuleCollection Type="Exe" EnforcementMode="Enabled">
<FilePathRule Id="{ALLOW_EXE}" Name="Yoke QA allow all programs" Description="" UserOrGroupSid="S-1-1-0" Action="Allow"><Conditions><FilePathCondition Path="*" /></Conditions></FilePathRule>
<FilePathRule Id="{DENY_PYTHON}" Name="Yoke QA deny uv Python" Description="" UserOrGroupSid="TEST_SID" Action="Deny"><Conditions><FilePathCondition Path="UV_ROOT\\*" /></Conditions><Exceptions><FilePathCondition Path="PROBE_PYTHON" /></Exceptions></FilePathRule>
</RuleCollection>
<RuleCollection Type="Script" EnforcementMode="Enabled">
<FilePathRule Id="{ALLOW_SCRIPT}" Name="Yoke QA allow all scripts" Description="" UserOrGroupSid="S-1-1-0" Action="Allow"><Conditions><FilePathCondition Path="*" /></Conditions></FilePathRule>
<FilePathRule Id="{DENY_YOKE}" Name="Yoke QA deny yoke.cmd" Description="" UserOrGroupSid="TEST_SID" Action="Deny"><Conditions><FilePathCondition Path="YOKE_CMD" /></Conditions><Exceptions><FilePathCondition Path="PROBE_PYTHON" /></Exceptions></FilePathRule>
</RuleCollection>
<RuleCollection Type="Appx" EnforcementMode="Enabled">
<FilePublisherRule Id="{ALLOW_APPX}" Name="Yoke QA allow packaged apps" Description="" UserOrGroupSid="S-1-1-0" Action="Allow"><Conditions><FilePublisherCondition PublisherName="*" ProductName="*" BinaryName="*"><BinaryVersionRange LowSection="0.0.0.0" HighSection="*" /></FilePublisherCondition></Conditions></FilePublisherRule>
</RuleCollection>
</AppLockerPolicy>"""

APPLOCKER_HELPERS = r"""
function Get-YokeAppLockerIds {
 try {$local=[xml](Get-AppLockerPolicy -Local -Xml -ErrorAction Stop)} catch {return @('unreadable')}
 @($local.SelectNodes('//*[@Id]') | ForEach-Object {$_.Id.ToLowerInvariant()} | Sort-Object)
}
function Set-YokeAppLockerPolicy([string]$xml) {
 $file=Join-Path $env:TEMP ('yoke-applocker-'+[Guid]::NewGuid().ToString('N')+'.xml')
 try {
  [IO.File]::WriteAllText($file,$xml,[Text.UTF8Encoding]::new($false))
  # A write that races the running AppIDSvc can fail transiently; three tries.
  for($try=1;;$try++){
   try {Set-AppLockerPolicy -XmlPolicy $file -ErrorAction Stop; break}
   catch {if($try -ge 3){throw}; Start-Sleep -Seconds 2}
  }
 } finally {Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue}
}
function Get-YokeSrpRuleCount {
 $root='HKLM:\SOFTWARE\Policies\Microsoft\Windows\SrpV2'
 # AppIDSvc rewrites these keys while it applies a policy; a read that races
 # it ("No more data is available") counts as not yet clear, and callers retry.
 try {
  if(!(Test-Path -LiteralPath $root)){return 0}
  @(Get-ChildItem -LiteralPath $root -ErrorAction Stop | ForEach-Object {Get-ChildItem -LiteralPath $_.PSPath -ErrorAction Stop}).Count
 } catch {return -1}
}
"""

APPLOCKER_SETUP = (
    PROFILE_HELPERS
    + APPLOCKER_HELPERS
    + r"""
$sid=Get-YokeUserSid $testUser
$profilePath=Resolve-YokeProfile $sid
if(!$profilePath){throw 'applocker_test_profile_missing: provision the test user profile, then retry'}
$probes=$golden+'.probes'
$python=if(Test-Path -LiteralPath $probes){@((Get-Content -Raw -LiteralPath $probes | ConvertFrom-Json).probes)[0].argv[0]}else{$null}
if(!$python){throw 'machine_fixture_probe_interpreter_unknown: capture a sealed golden so its probes name the interpreter, then retry'}
$escape={param($value) [Security.SecurityElement]::Escape([string]$value)}
$xml=POLICY.Replace('TEST_SID',$sid).Replace('UV_ROOT',(& $escape (Join-Path $profilePath 'AppData\Roaming\uv'))).Replace('YOKE_CMD',(& $escape (Join-Path $profilePath '.local\bin\yoke.cmd'))).Replace('PROBE_PYTHON',(& $escape $python))
if(((Get-YokeAppLockerIds) -join ',') -ne RULE_IDS){Set-YokeAppLockerPolicy $xml}
if((Get-Service AppIDSvc).Status -ne 'Running'){Start-Service AppIDSvc}
$verify=[ordered]@{rules=@(Get-YokeAppLockerIds);appidsvc=[string](Get-Service AppIDSvc).Status}
if(($verify.rules -join ',') -ne RULE_IDS -or $verify.appidsvc -ne 'Running'){throw 'applocker_not_applied: inspect the local AppLocker policy and AppIDSvc'}
"""
)

APPLOCKER_UNDO = (
    APPLOCKER_HELPERS
    + r"""
# An empty document leaves existing collections in place; replace each one.
if(@(Get-YokeAppLockerIds).Count -or (Get-YokeSrpRuleCount)){Set-YokeAppLockerPolicy EMPTY_POLICY}
# The running AppIDSvc applies a policy change asynchronously.
$deadline=[DateTime]::UtcNow.AddSeconds(60)
while((@(Get-YokeAppLockerIds).Count -or (Get-YokeSrpRuleCount)) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 500}
# AppIDSvc stays as Windows runs it: Windows 11 starts it with no rules, and
# without rules AppLocker enforces nothing (decision request 16091).
$verify=[ordered]@{rules=@(Get-YokeAppLockerIds);srp_rules=(Get-YokeSrpRuleCount)}
if($verify.rules.Count -or $verify.srp_rules){throw ('applocker_not_undone: clear the local AppLocker policy; '+($verify | ConvertTo-Json -Compress))}
"""
)


EMPTY_POLICY = (
    '<AppLockerPolicy Version="1">'
    + "".join(
        f'<RuleCollection Type="{kind}" EnforcementMode="NotConfigured" />'
        for kind in ("Appx", "Dll", "Exe", "Msi", "Script")
    )
    + "</AppLockerPolicy>"
)
APPLOCKER_UNDO = APPLOCKER_UNDO.replace("EMPTY_POLICY", "'" + EMPTY_POLICY + "'")


def applocker_setup() -> str:
    from yoke_harness.native_windows.powershell import quote

    return APPLOCKER_SETUP.replace("POLICY", quote(APPLOCKER_POLICY), 1).replace(
        "RULE_IDS", quote(",".join(APPLOCKER_RULE_IDS))
    )
