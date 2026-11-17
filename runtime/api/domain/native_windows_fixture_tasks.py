"""Real standard-SSH recovery and task/profile roundtrip on disposable guests."""

import json
from uuid import uuid4

from yoke_harness.native_windows.baseline import profile_operation
from yoke_harness.native_windows.tasks import HELPERS, remove_owned_task
from yoke_harness.native_windows.transport import quote
from yoke_harness.ssh_native_windows_host_operations import SshNativeWindowsHostOperations


def verify_standard_task_operations(settings, key, password):
    control = SshNativeWindowsHostOperations(
        settings=settings, key_path=key, secret_values=(password,),
    )
    lease = uuid4().hex
    # Production binding invokes the fixed SYSTEM task through standard SSH;
    # its receipt proves execution, rather than just task registration.
    control.bind_qa_lease(lease)
    name = "YokeFixture-" + uuid4().hex
    extra = name + "-extra"
    golden = r"C:\YokeQa\goldens" + "\\" + name
    sealed = golden + "\\sealed"
    original = control._run("@{path=[Environment]::GetEnvironmentVariable('Path','User')} | ConvertTo-Json -Compress")
    assert original.returncode == 0, original.stderr
    saved_path = json.loads(original.stdout)["path"]
    restore_path = "$null" if saved_path is None else quote(saved_path)
    try:
        created = control._run(HELPERS + f"""
$task=New-YokeInteractiveTask {quote(name)} '-NoProfile -Command exit' 60
if(!(Test-YokeTaskOwner $task) -or $task.Definition.Principal.LogonType -ne 3 -or $task.Definition.Principal.RunLevel -ne 0){{throw 'owned limited interactive task not established'}}
""")
        assert created.returncode == 0, created.stderr
        foreign = control._run(remove_owned_task("YokeQaMachineSettings"))
        assert foreign.returncode != 0 and "windows_task_owner_refused" in foreign.stderr
        captured = profile_operation(control, "capture", golden)
        assert captured.ok, captured.evidence
        # Sealing here is fixture-owned; production capture seals only after
        # its separate CLI and browser identity checks have also completed.
        changed = control._run(HELPERS + f"""
Set-Content -LiteralPath {quote(sealed)} -Value fixture
$task=Get-YokeTask {quote(name)}
$definition=$task.Definition; $definition.Actions.Item(1).Arguments='-NoProfile -Command wrong'
$schedule.GetFolder('\').RegisterTaskDefinition({quote(name)},$definition,4,$taskIdentity.User.Value,$null,3,$null) | Out-Null
New-YokeInteractiveTask {quote(extra)} '-NoProfile -Command exit' 60 | Out-Null
[Environment]::SetEnvironmentVariable('Path','fixture-path-change','User')
""")
        assert changed.returncode == 0, changed.stderr
        restored = profile_operation(control, "reset", golden)
        assert restored.ok, restored.evidence
        verified = control._run(HELPERS + f"""
$task=Get-YokeTask {quote(name)}
if(!$task -or $task.Definition.Actions.Item(1).Arguments -cne '-NoProfile -Command exit'){{throw 'saved task XML not restored'}}
if(Get-YokeTask {quote(extra)}){{throw 'new task not removed'}}
@{{path=[Environment]::GetEnvironmentVariable('Path','User');fixedExists=($null -ne (Get-YokeTask 'YokeQaMachineSettings'))}} | ConvertTo-Json -Compress
""")
        assert verified.returncode == 0, verified.stderr
        facts = json.loads(verified.stdout)
        assert facts["path"] == saved_path
        assert facts["fixedExists"] is True
    finally:
        cleanup = control._run(
            remove_owned_task(name) + remove_owned_task(extra)
            + f"\nRemove-Item -LiteralPath {quote(golden)} -Recurse -Force -ErrorAction SilentlyContinue"
            + f"\n[Environment]::SetEnvironmentVariable('Path',{restore_path},'User')"
        )
        assert cleanup.returncode == 0, cleanup.stderr
