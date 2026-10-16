"""Executable recovery journeys on the campaign's isolated Test Machine."""

from copy import deepcopy
import shlex

from yoke_core.domain.installer_campaign_issue_sync_cases import issue_sync_cases
from yoke_core.domain.installer_campaign_install_health_cases import (
    install_health_cases,
)
from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.installer_campaign_plan_common import (
    FRESH_HOST,
    PUBLIC_INSTALL,
    SHELL_PRECONFIGURED,
    action,
    current_release_setup,
    terminal_case,
    terminal_recipe,
)
from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN
from yoke_core.domain.machine_qa_fixture_paths import FIXTURE_ROOT


_LOCAL_SETUP = (
    f"{YOKE_BIN} setup --local --non-interactive --yes "
    "--admin-name 'Installer QA' --project-mode machine-only "
    "--machine-github disabled"
)
_INSTALL_ONLY = (
    "/usr/bin/curl -fsSL {{installer_base_url}}/install "
    f"-o {FIXTURE_ROOT}/install/recovery-install; "
    "/usr/bin/env YOKE_INSTALL_BASE_URL={{installer_base_url}} "
    "YOKE_CHANNEL={{release_channel}} YOKE_NO_SETUP=1 "
    f"/bin/sh {FIXTURE_ROOT}/install/recovery-install --yes --no-setup"
)


def _command_case(
    position, key, command, *, instructions, outcome, execution_mode="ssh-command"
):
    return terminal_case(
        position,
        key,
        "terminal-check",
        instructions=instructions,
        expected_outcome=outcome,
        entry_surface=f"set -eu; {command}; printf '%s\\n' {shlex.quote(key)}",
        required_completion=key,
        host_baselines=[FRESH_HOST],
        method_config=terminal_recipe(
            actions=[action(key, capture=False)],
            expected_text=[key],
            capture_checkpoints=[],
            execution_mode=execution_mode,
            setup_operations=current_release_setup(key, path_ready=True),
            notes="Run only on the leased Test Machine. Restore its declared baseline afterward.",
        ),
    )


def _hosted_case(position, key, prefix, *, instructions, outcome, after_installer=":"):
    source = next(
        row
        for row in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES
        if row["case_key"] == "cold-start-hosted"
    )
    config = deepcopy(source["method_config"]["baseline_configs"][SHELL_PRECONFIGURED])
    config["setup_operations"] = current_release_setup(key, path_ready=True)
    config["expected_text"].append(key + "-prepared")
    config["expected_text"].append(key + "-ready")
    config["actions"].append(
        action(
            key + "-ready",
            ready_text=[key + "-ready"],
            ready_timeout_seconds=45,
        )
    )
    config["notes"] = instructions
    return terminal_case(
        position,
        key,
        "terminal-check",
        instructions=instructions,
        expected_outcome=outcome,
        entry_surface=(
            f"set -eu; {prefix}; printf '%s\\n' {shlex.quote(key + '-prepared')}; "
            + PUBLIC_INSTALL
            + f"; {after_installer}; printf '%s\\n' "
            + shlex.quote(key + "-prepared")
            + " "
            + shlex.quote(key + "-ready")
        ),
        required_completion="complete-onboarding",
        host_baselines=[FRESH_HOST],
        method_config=config,
    )


_STALE_RELEASE_SCRIPT = """
import json, re, sys
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
from packaging.utils import parse_wheel_filename
from packaging.version import Version
def previous_release():
    origin, channel = sys.argv[1:]
    with urlopen(origin + '/dist/channels/' + channel + '.json', timeout=60) as response:
        current = json.load(response)
    with urlopen(current['index_url'].rstrip('/') + '/yoke-cli/', timeout=60) as response:
        html = response.read().decode()
    versions = set()
    for link in re.findall(r'href=[\\\"\\\']([^\\\"\\\']+)', html):
        filename = unquote(urlparse(link).path.rsplit('/', 1)[-1])
        if filename.endswith('.whl'):
            versions.add(parse_wheel_filename(filename)[1])
    older = [value for value in versions if value < Version(current['version'])]
    if not older:
        sys.exit('stale_release_unavailable: publish a predecessor to this distribution before rerunning this case')
    print(str(Version(current['version'])), max(older))
try:
    previous_release()
except (OSError, ValueError, KeyError):
    sys.exit('stale_release_lookup_failed: verify the declared distribution channel and wheel index before rerunning')
"""
_STALE_PREPARE = (
    '_campaign_python="$(uv tool dir)/yoke-cli/bin/python3"; '
    '_campaign_selection=$("$_campaign_python" -c '
    + shlex.quote(_STALE_RELEASE_SCRIPT)
    + " {{installer_base_url}} {{release_channel}}); "
    'read -r _campaign_expected _campaign_previous <<< "$_campaign_selection"; '
    + _INSTALL_ONLY.replace(
        "YOKE_NO_SETUP=1",
        'YOKE_NO_SETUP=1 YOKE_VERSION="$_campaign_previous"',
    )
    + f'; test "$({YOKE_BIN} --version)" = "$_campaign_previous"'
)

STALE_REINSTALL = _command_case(
    11,
    "stale-reinstall",
    _STALE_PREPARE
    + "; "
    + _INSTALL_ONLY
    + f'; test "$({YOKE_BIN} --version)" = "$_campaign_expected"',
    instructions=(
        "Resolve a published predecessor from this target's wheel index. Install it without setup, "
        "then reinstall the target release. Retain both version observations and restoration evidence."
    ),
    outcome="A real older published install is replaced by the target installer with no silent failure.",
)

LOCAL_HOSTED_BACKUP = _hosted_case(
    12,
    "local-hosted-backup",
    _LOCAL_SETUP
    + f"; {YOKE_BIN} universe export --out {FIXTURE_ROOT}/local-backup.tar --json"
    + f"; test -s {FIXTURE_ROOT}/local-backup.tar",
    after_installer=f"test -s {FIXTURE_ROOT}/local-backup.tar",
    instructions=(
        "Create a local universe on the isolated host, export a portable backup, then switch to the "
        "declared hosted target through its real approval and Apply path. Keep backup and setup proof."
    ),
    outcome="Local backup exists and the same machine completes hosted setup under its real approval obligations.",
)

LOCAL_HOSTED_NO_BACKUP = _hosted_case(
    13,
    "local-hosted-no-backup",
    _LOCAL_SETUP,
    instructions=(
        "Create a local universe on the isolated host, then choose hosted setup without exporting "
        "a backup. Follow the real browser approval and Apply path and preserve the selected choice."
    ),
    outcome="The no-backup local-to-hosted path completes without inventing a backup or bypassing approval.",
)

SECOND_MACHINE_JOIN = _hosted_case(
    14,
    "second-machine-join",
    'test ! -e "$HOME/.yoke/config.json"',
    instructions=(
        "Run on a second registered physical Test Machine after the first machine has joined the "
        "same organization. Pin that second machine through the saved case's machine constraint. "
        "Record distinct machine identities and preserved shared project choices. A reset of the "
        "first machine is not second-machine proof."
    ),
    outcome="A distinct second physical machine joins the same organization and retains project facts with its own readiness evidence.",
)

_UNINSTALL_WAIT_SCRIPT = """
import pathlib, sys, time
launcher = pathlib.Path(sys.argv[1])
deadline = time.monotonic() + 120
print('Waiting by design: deferred CLI uninstall; checking launcher removal for at most 120s.', flush=True)
while launcher.exists():
    if time.monotonic() >= deadline:
        sys.exit('uninstall_handoff_incomplete: inspect the uninstall result log before rerunning')
    time.sleep(0.25)
"""
UNINSTALL = _command_case(
    15,
    "uninstall",
    _LOCAL_SETUP
    + f"; {YOKE_BIN} uninstall --no-backup --projects none --yes"
    + "; python3 -c "
    + shlex.quote(_UNINSTALL_WAIT_SCRIPT)
    + f' {YOKE_BIN}; test ! -f "$HOME/.yoke/config.json"',
    instructions=(
        "Install and configure a local machine-only universe on the isolated host. Uninstall with "
        "explicit no-backup and no-project choices. Verify launcher and machine config removal "
        "and inspect hook/permission cleanup without reading credential contents."
    ),
    outcome="Uninstall completes with explicit data choices and removes the launcher and machine configuration.",
)

_LATE_HARNESS_SCRIPT = """
import os, pathlib, shutil, subprocess, sys
from yoke_contracts.codex_config_posture import changed, plan
from yoke_contracts.codex_hook_trust_store import inspect_hook_file_trust
binary = shutil.which('codex')
if not binary:
    sys.exit('late_harness_fixture_missing: install and sign in to Codex on the dedicated Test Machine before rerunning')
original = pathlib.Path(binary)
backup = original.with_name(original.name + '.installer-qa-saved')
home = pathlib.Path(sys.argv[2])
if backup.exists() or home.exists():
    sys.exit('late_harness_fixture_interrupted: restore the executable and reset the owned fixture before rerunning')
environment = os.environ.copy()
environment['CODEX_HOME'] = str(home)
try:
    original.rename(backup)
    result = subprocess.run(sys.argv[1], shell=True, timeout=600, env=environment)
except (OSError, subprocess.SubprocessError):
    sys.exit('late_harness_fixture_failed: repair the fixture executable or setup timeout before rerunning')
finally:
    if backup.exists():
        try:
            backup.rename(original)
        except OSError:
            sys.exit('late_harness_restore_failed: restore codex.installer-qa-saved to codex before another test')
if result.returncode:
    sys.exit('late_harness_setup_failed: inspect the setup refusal and rerun after recovery')
try:
    version = subprocess.run([str(original), '--version'], timeout=60, env=environment)
    home.mkdir(parents=True, exist_ok=True)
    discovery = subprocess.run(sys.argv[1], shell=True, timeout=600, env=environment)
except (OSError, subprocess.SubprocessError):
    sys.exit('late_harness_discovery_failed: inspect the executable or setup timeout before rerunning')
if version.returncode:
    sys.exit('late_harness_executable_unusable: repair Codex before rerunning')
if discovery.returncode:
    sys.exit('late_harness_discovery_failed: inspect setup refusal and rerun after recovery')
config = home / 'config.toml'
if not config.is_file():
    sys.exit('late_harness_permissions_missing: run setup after installing Codex')
try:
    _, record = plan(config.read_text())
except (OSError, ValueError):
    sys.exit('late_harness_config_unreadable: repair Codex config before rerunning')
if changed(record) or record['conflicts']:
    sys.exit('late_harness_permissions_unready: resolve the reported Codex posture before rerunning')
trust = inspect_hook_file_trust(home / 'hooks.json', config_path=config)
if not trust.approved:
    sys.exit('late_harness_hooks_unready: reconcile and trust the installed Codex hooks before rerunning')
"""
LATE_HARNESS = _command_case(
    16,
    "late-harness-discovery",
    '"$(uv tool dir)/yoke-cli/bin/python3" -c '
    + shlex.quote(_LATE_HARNESS_SCRIPT)
    + " "
    + shlex.quote(_LOCAL_SETUP)
    + f" {FIXTURE_ROOT}/late-codex",
    instructions=(
        "Use a disposable CODEX_HOME and temporarily preserve its executable outside discovery while configuring Yoke, "
        "then restore the executable and rerun public setup for the newly available harness. Verify native version, trust, hooks "
        "and permission pickup in a real session. Keep sign-in data untouched and restore the "
        "executable even if setup fails. Never move the personal Codex home. CLI presence alone is not a passing discovery result."
    ),
    outcome=(
        "A harness made available after setup has approved hooks and unattended permissions. "
        "The exploration mission separately proves actual session delivery."
    ),
)


INSTALLER_RECOVERY_CASES = (
    (
        STALE_REINSTALL,
        LOCAL_HOSTED_BACKUP,
        LOCAL_HOSTED_NO_BACKUP,
        SECOND_MACHINE_JOIN,
        UNINSTALL,
        LATE_HARNESS,
    )
    + install_health_cases(_command_case)
    + issue_sync_cases(_command_case, _LOCAL_SETUP)
)


def recovery_cases(*, primary_machine: str, joining_machine: str):
    """Bind physical hosts explicitly; resetting one host cannot prove a join."""
    if not primary_machine or not joining_machine or primary_machine == joining_machine:
        raise ValueError(
            "installer_campaign_hosts_required: select two distinct registered "
            "Test Machines before exporting the campaign."
        )
    cases = deepcopy(INSTALLER_RECOVERY_CASES)
    for case in cases:
        case["method_config"]["machine"] = (
            joining_machine
            if case["case_key"] == "second-machine-join"
            else primary_machine
        )
    return cases
