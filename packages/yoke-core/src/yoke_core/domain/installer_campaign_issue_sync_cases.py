"""Installed CLI proof that issue mirroring starts off and unsafe enables refuse."""

import shlex

from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN
from yoke_core.domain.installer_campaign_plan_common import action


ISSUE_SYNC_DEFAULT_SCRIPT = r"""
import json, subprocess, sys
binary = sys.argv[1]
def call(*args):
    try:
        result = subprocess.run([binary, *args, '--json'], capture_output=True, text=True, timeout=60)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        sys.exit('issue_sync_probe_unreadable: inspect the installed CLI and local setup report before retrying')
    return result, payload
result, payload = call('projects', 'create', '--slug', 'mirror-proof', '--name', 'Mirror proof', '--public-item-prefix', 'MIR')
if result.returncode or not payload.get('success'):
    sys.exit('issue_sync_fixture_create_failed: restore the declared baseline and inspect projects create before retrying')
result, payload = call('projects', 'get', '--project', 'mirror-proof', '--field', 'github_sync_mode')
if result.returncode or payload.get('result', dict()).get('value') != 'disabled':
    sys.exit('issue_sync_default_enabled: retain the project response and repair the project default before retrying')
result, payload = call('projects', 'update', '--slug', 'mirror-proof', '--name', 'Mirror proof', '--github-sync-mode', 'enabled')
if not result.returncode or 'active, verified' not in json.dumps(payload):
    sys.exit('issue_sync_permission_gate_missing: retain the update refusal and repair verified App admission before retrying')
result, payload = call('projects', 'get', '--project', 'mirror-proof', '--field', 'github_sync_mode')
if result.returncode or payload.get('result', dict()).get('value') != 'disabled':
    sys.exit('issue_sync_refusal_changed_mode: retain the project response and restore disabled mode before retrying')
print('issue mirroring remained disabled; deliberate unbound enable refused')
"""


def issue_sync_cases(command_case, local_setup):
    """Use the existing campaign's command recipe and isolated local setup."""
    case = command_case(
        25,
        "issue-sync-default",
        local_setup
        + '; "$(uv tool dir)/yoke-cli-releases/current/tools/yoke-cli/bin/python3" -c '
        + shlex.quote(ISSUE_SYNC_DEFAULT_SCRIPT)
        + f" {YOKE_BIN}",
        execution_mode="terminal",
        instructions=(
            "Create an isolated local project using the installed candidate. "
            "Verify disabled mode before and after a deliberate enable without App access. "
            "Keep the named refusal; restore the declared baseline afterward. "
            "Real active-binding, agent opt-in and first-issue URL proof remains "
            "with the installer exploration and its approved repository fixture."
        ),
        outcome="A new project stays disabled and unbound enable refuses with binding recovery.",
    )
    case["method_config"]["actions"] = [
        action(
            "issue-sync-default",
            ready_text=("issue-sync-default",),
            ready_timeout_seconds=300,
        )
    ]
    return (case,)
