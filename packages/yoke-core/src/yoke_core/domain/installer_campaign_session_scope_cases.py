"""Installed CLI proof that sessions outside a project keep organization scope.

Each case runs the installed candidate on the campaign Test Machine: a
session started outside any project belongs to its authority's organization
on every declared harness, reinstallation keeps that scope, and the same
session claims and releases a project item without changing its scope. The host
adapter expands braces in ``entry_surface``, so the embedded script uses none.
"""

import shlex

from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN
from yoke_core.domain.installer_campaign_plan_common import action
from yoke_core.domain.session_probe import PROBE_MAX_LIFETIME_SECONDS


SESSION_SCOPE_SCRIPT = r"""
import json, os, re, subprocess, sys, tempfile, time, uuid
binary, mode = sys.argv[1], sys.argv[2]
probe_window_seconds = PROBE_WINDOW_SECONDS
saved = os.path.join(tempfile.gettempdir(), 'yoke-session-scope-proof')
ambient = ('YOKE_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'CURSOR_CONVERSATION_ID')
harnesses = (('claude-code', 'anthropic', 'claude-sonnet-5-5'), ('codex', 'openai', 'gpt-5.6-terra'), ('cursor', 'cursor', 'claude-sonnet-5-5'))
def call(args, session, cwd, as_json=True):
    env = dict(os.environ)
    for name in ambient:
        env.pop(name, None)
    if session:
        env['YOKE_SESSION_ID'] = session
    argv = [binary] + list(args) + (['--json', '--full'] if as_json else [])
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=cwd, env=env)
    except (OSError, subprocess.TimeoutExpired):
        sys.exit('session_scope_probe_unreadable: inspect the installed CLI and local setup report before retrying')
    try:
        payload = json.loads(result.stdout) if as_json else dict()
    except ValueError:
        payload = dict()
    return result, payload if isinstance(payload, dict) else dict()
def begin(harness, session, folder, required=True):
    executor, provider, model = harness
    result, payload = call(['sessions', 'begin', '--executor', executor, '--provider', provider, '--requested-model', model, '--workspace', folder], session, folder)
    if required and (result.returncode or not payload.get('success')):
        sys.exit('session_scope_begin_failed: retain the ' + executor + ' registration refusal and repair session registration before retrying')
def scope(session, folder):
    result, payload = call(['sessions', 'identity'], session, folder)
    found = payload.get('result') or dict()
    if result.returncode or not found:
        sys.exit('session_scope_identity_unreadable: retain the identity read and repair session identity before retrying')
    return found.get('project_id'), found.get('org_id'), found.get('scope_kind')
def require_org(session, folder, label):
    project, org, kind = scope(session, folder)
    if project is not None or org is None or kind != 'org':
        sys.exit('session_scope_not_org: ' + label + ' has project ' + str(project) + ', org ' + str(org) + ' and scope ' + str(kind) + '; retain the identity read and repair scope resolution before retrying')
def claim(ref, session, folder):
    result, payload = call(['claims', 'work', 'acquire', '--item', ref, '--reason', 'session-scope-proof'], session, folder)
    named = (payload.get('error') or dict()).get('code') or ''
    if not named:
        found = re.search(r'(?m)^([A-Z][A-Z_]+):', result.stderr)
        named = found.group(1) if found else ''
    text = result.stdout + result.stderr
    print('claim ' + ref + ' exit ' + str(result.returncode) + ':\n' + text, flush=True)
    return result.returncode, named
outside = tempfile.mkdtemp(prefix='outside-project-')
if mode == 'harnesses':
    started = []
    for harness in harnesses:
        session = str(uuid.uuid4())
        begin(harness, session, outside)
        require_org(session, outside, 'the ' + harness[0] + ' session')
        result, payload = call(['sessions', 'list', '--liveness', 'active', '--session', session], session, outside)
        if session not in json.dumps(payload):
            sys.exit('session_scope_roster_hidden: the ' + harness[0] + ' session is missing from sessions list; retain the listing and repair roster visibility before retrying')
        started.append((harness, session))
    # Every session read hides a session that ends inside the probe window
    # without a tool call (a harness startup probe), so outlive that window.
    time.sleep(probe_window_seconds)
    for harness, session in started:
        call(['sessions', 'end-if-empty', '--triggered-by', 'session-scope-proof'], session, outside)
        result, payload = call(['sessions', 'list', '--liveness', 'ended', '--session', session], session, outside)
        if session not in json.dumps(payload):
            sys.exit('session_scope_history_hidden: the ended ' + harness[0] + ' session is missing from session history; retain the listing and repair history visibility before retrying')
    print('outside-project sessions belong to the organization on every harness')
elif mode == 'reinstall-before':
    session = str(uuid.uuid4())
    begin(harnesses[0], session, outside)
    require_org(session, outside, 'the session before reinstalling')
    with open(saved, 'w') as handle:
        handle.write(session)
    print('outside-project session recorded before reinstalling')
elif mode == 'reinstall-after':
    try:
        with open(saved) as handle:
            session = handle.read().strip()
    except OSError:
        sys.exit('session_scope_state_missing: rerun this case from its first step; the pre-reinstall session id was not saved')
    require_org(session, outside, 'the session after reinstalling')
    begin(harnesses[0], session, outside, required=False)
    require_org(session, outside, 'the re-registered session')
    print('reinstallation kept the outside-project session in its organization')
elif mode == 'first-work':
    session = str(uuid.uuid4())
    begin(harnesses[0], session, outside)
    require_org(session, outside, 'the outside-project session')
    result, payload = call(['projects', 'create', '--slug', 'scope-proof', '--name', 'Scope proof', '--public-item-prefix', 'SCP'], session, outside)
    if result.returncode or not payload.get('success'):
        sys.exit('first_work_fixture_create_failed: restore the declared baseline and inspect projects create before retrying')
    spec = os.path.join(outside, 'spec.md')
    with open(spec, 'w') as handle:
        handle.write('Prove a session outside the project claims its item.\n')
    result, _ = call(['items', 'create', '--title', 'Scope proof', '--workflow', 'task', '--spec-file', spec, '--execution-instructions-considered', '--project', 'scope-proof'], session, outside)
    found = re.search(r'SCP-[0-9]+', result.stdout)
    if result.returncode or found is None:
        print('items create exit ' + str(result.returncode) + ':', result.stdout, result.stderr, sep='\n', flush=True)
        sys.exit('first_work_fixture_item_failed: retain the item create output and repair item creation before retrying')
    ref = found.group(0)
    code, named = claim(ref, session, outside)
    if code and not named:
        sys.exit('first_work_claim_unnamed: retain the claim output; a session outside the project must claim the item or refuse with a named reason')
    require_org(session, outside, 'the outside-project session after its claim')
    if code:
        print('the outside-project session kept its organization scope; its claim refused only by ' + named)
    else:
        result, _ = call(['claims', 'work', 'release', '--item', ref, '--reason', 'session-scope-proof'], session, outside)
        if result.returncode:
            print('release exit ' + str(result.returncode) + ':', result.stdout, result.stderr, sep='\n', flush=True)
            sys.exit('first_work_release_failed: retain the release output and repair claims work release before retrying')
        print('the outside-project session claimed and released the item and kept its organization scope')
else:
    sys.exit('session_scope_mode_unknown: name harnesses, reinstall-before, reinstall-after or first-work')
""".replace("PROBE_WINDOW_SECONDS", str(PROBE_MAX_LIFETIME_SECONDS + 5))


def _probe(mode):
    return (
        '"$(uv tool dir)/yoke-cli-releases/current/tools/yoke-cli/bin/python3" -c '
        + shlex.quote(SESSION_SCOPE_SCRIPT)
        + f" {YOKE_BIN} {mode}"
    )


def session_scope_cases(command_case, local_setup, install_only):
    """Use the campaign's command recipe, isolated local setup and reinstall."""
    specs = (
        (
            26,
            "outside-project-sessions",
            f"{local_setup}; {_probe('harnesses')}",
            "Register one session per declared harness (Claude Code, Codex, Cursor) "
            "from a fresh folder outside any project with the installed candidate. "
            "Read each identity and the active roster, wait past the startup-probe "
            "window, end each session, then read ended history. Restore the declared "
            "baseline afterward.",
            "Every harness session belongs to the organization, with no project, "
            "and appears in sessions list and ended history.",
        ),
        (
            27,
            "outside-project-reinstall",
            f"{local_setup}; {_probe('reinstall-before')}; {install_only}; "
            f"{_probe('reinstall-after')}",
            "Register a session outside any project, reinstall the candidate without "
            "setup, then read and re-register the same session. Restore the declared "
            "baseline afterward.",
            "Reinstallation and re-registration keep the session's organization scope.",
        ),
        (
            28,
            "outside-project-first-work",
            f"{local_setup}; {_probe('first-work')}",
            "Create an isolated local project and task item, claim it from a session "
            "outside any project, read its identity, then release the claim. Model "
            "admission and done state belong to the installer exploration. Restore "
            "the declared baseline afterward.",
            "The outside session has organization scope with no project before and "
            "after the claim. It claims and releases the item, or the claim refuses "
            "only with a named reason such as model admission.",
        ),
    )
    cases = []
    for position, key, command, instructions, outcome in specs:
        case = command_case(
            position,
            key,
            command,
            execution_mode="terminal",
            instructions=instructions,
            outcome=outcome,
        )
        case["method_config"]["actions"] = [
            action(key, ready_text=(key,), ready_timeout_seconds=300)
        ]
        cases.append(case)
    return tuple(cases)


__all__ = ["SESSION_SCOPE_SCRIPT", "session_scope_cases"]
