"""Task Scheduler 2.0 COM operations under the standard SSH token.

ScheduledTasks cmdlets use CIM, which standard OpenSSH users cannot access.
The native Scheduler service enforces each task's existing security descriptor.
"""

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.display_geometry import CONSOLE_DISPLAY_TASK
from yoke_harness.native_windows.transport import quote


HELPERS = r"""
$schedule=New-Object -ComObject Schedule.Service
$schedule.Connect()
$taskIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
function Test-YokeTaskOwner($task) {
 $owner=$task.Definition.Principal.UserId
 if(!$owner){return $false}
 try {
  $sid=if($owner -match '^S-1-'){$owner}else{
   ([Security.Principal.NTAccount]::new($owner)).Translate([Security.Principal.SecurityIdentifier]).Value
  }
 } catch [Security.Principal.IdentityNotMappedException] {return $false}
 return $sid -eq $taskIdentity.User.Value
}
function Get-YokeTask($path) {
 try {return $schedule.GetFolder('\').GetTask($path)}
 catch {
  $failure=$_.Exception
  while($failure.InnerException){$failure=$failure.InnerException}
  if($failure.HResult -in @(-2147024894,-2147024893)){return $null}
  throw
 }
}
function Remove-YokeTask($path) {
 $task=Get-YokeTask $path
 if(!$task){return}
 if(!(Test-YokeTaskOwner $task)){throw 'windows_task_owner_refused: preserve the foreign task and select an owned task'}
 if($task.State -eq 4){$task.Stop(0)}
 $split=$task.Path.LastIndexOf('\')
 $folder=if($split -eq 0){'\'}else{$task.Path.Substring(0,$split)}
 $schedule.GetFolder($folder).DeleteTask($task.Name,0)
}
function Get-YokeOwnedTasks($folder) {
 foreach($task in $folder.GetTasks(1)) {
  if($task.Path -ne '\CONSOLE_DISPLAY_TASK' -and (Test-YokeTaskOwner $task)){$task}
 }
 foreach($child in $folder.GetFolders(0)){Get-YokeOwnedTasks $child}
}
function Get-YokeTaskFolder($path) {
 if(!$path.StartsWith('\')){throw 'windows_task_path_invalid: use a saved absolute task folder'}
 $folder=$schedule.GetFolder('\')
 foreach($part in $path.Split('\')) {
  if(!$part){continue}
  if($part -in @('.','..')){throw 'windows_task_path_invalid: remove parent traversal'}
  try {$folder=$folder.GetFolder($part)} catch {
   $failure=$_.Exception
   while($failure.InnerException){$failure=$failure.InnerException}
   if($failure.HResult -notin @(-2147024894,-2147024893)){throw}
   $folder=$folder.CreateFolder($part,$null)
  }
 }
 return $folder
}
function New-YokeInteractiveTask($name,$path,$arguments,$seconds) {
 if(Get-YokeTask $name){throw 'windows_task_exists: preserve the existing task and choose a fresh task name'}
 $definition=$schedule.NewTask(0)
 $definition.Principal.UserId=$taskIdentity.User.Value
 $definition.Principal.LogonType=3
 $definition.Principal.RunLevel=0
 $definition.Settings.ExecutionTimeLimit='PT'+$seconds+'S'
 $definition.Settings.DisallowStartIfOnBatteries=$false
 $definition.Settings.StopIfGoingOnBatteries=$false
 $definition.Settings.AllowDemandStart=$true
 $action=$definition.Actions.Create(0)
 $action.Path=$path; $action.Arguments=$arguments
 # TASK_CREATE, INTERACTIVE_TOKEN; never update a colliding task or elevate.
 $schedule.GetFolder('\').RegisterTaskDefinition($name,$definition,2,$taskIdentity.User.Value,$null,3,$null)
}
function Restore-YokeTask($row) {
 $definition=$schedule.NewTask(0)
 $definition.XmlText=$row.xml
 if(!(Test-YokeTaskOwner ([pscustomobject]@{Definition=$definition}))){throw 'windows_task_owner_refused: saved task must belong to the test user'}
 if($definition.Principal.LogonType -notin @(2,3) -or $definition.Principal.RunLevel -ne 0){
  throw 'windows_task_credentials_required: baseline tasks must use limited interactive or S4U logon without stored passwords'
 }
 $existing=Get-YokeTask ($row.path+$row.name)
 if($existing -and !(Test-YokeTaskOwner $existing)){throw 'windows_task_owner_refused: preserve the foreign task at the saved path'}
 # TASK_CREATE_OR_UPDATE | TASK_IGNORE_REGISTRATION_TRIGGERS.
 $folder=Get-YokeTaskFolder $row.path
 $folder.RegisterTaskDefinition($row.name,$definition,38,$taskIdentity.User.Value,$null,$definition.Principal.LogonType,$null) | Out-Null
}
""".replace("CONSOLE_DISPLAY_TASK", CONSOLE_DISPLAY_TASK)


def create_interactive_task(name, path, arguments, seconds):
    return HELPERS + f"$task=New-YokeInteractiveTask {quote(name)} {quote(path)} {quote(arguments)} {int(seconds)}; $task.Run($null) | Out-Null"


def remove_owned_task(name):
    return HELPERS + f"Remove-YokeTask {quote(name)}"


def require_task_result(control, result, *, phase):
    if result.returncode:
        raise HostControlLocalError(
            code="native_windows_task_failed", phase=phase,
            detail="Native Windows Task Scheduler operation failed.",
            recovery_hint="Inspect the native Scheduler error and existing task permissions; preserve task ownership and standard-user privileges, then retry.",
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
            secrets=getattr(control, "secret_values", ()),
        )
