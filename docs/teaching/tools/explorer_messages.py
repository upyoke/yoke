"""Named hook deliveries and concrete reply schemas, linked to their definitions."""

import ast
import re
from inventory import live_registries
from explorer_documents import REPO
from explorer_runtime import CORE, source_node, literal, add_reply_fields, HOOK_DESCRIPTIONS, CHECK_OUTPUT_TITLES

CONTRACTS = 'packages/yoke-contracts/src/yoke_contracts/'
HOOKS = 'packages/yoke-core/src/yoke_core/hooks/'
def add_hooks(add):
    from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING
    from yoke_contracts.hook_runner.guard_scope import applicable_chain, guard_scope

    messages, copies = {}, []
    events = {
        'PreToolUse': 'Before a tool runs', 'PostToolUse': 'After a tool runs',
        'PostToolUseFailure': 'When a tool fails', 'PermissionRequest': 'When permission is requested',
        'SessionStart': 'When a session starts', 'SessionEnd': 'When a session ends',
        'UserPromptSubmit': 'When you send a prompt', 'Stop': 'When the agent stops',
    }
    names = {
        'lint_shell_backtick_search': 'Check shell searches',
        'lint_local_privacy': 'Protect private local data',
        'lint_unmatched_path_glob': 'Check file patterns',
        'session_message_delivery': 'Incoming messages',
        'session_launch_attestation': 'Launch instructions',
        'session_broker_wake': 'Wake request', 'heartbeat': 'Update session activity',
        'observe_pre': 'Record tool activity', 'observe': 'Record tool results',
        'session_dispatch': 'Register or update the session',
        'session_resume_block': 'Resume context',
    }
    templates = {'session_launch_attestation': 'render_launch_instructions',
                 'session_broker_wake': '_render'}
    for scope in ('global', 'project'):
        prefix = 'hook-event:' + ('global:' if scope == 'global' else '')
        other = 'hook-event:' + ('' if scope == 'global' else 'global:')
        for event, matchers in HOOK_ORDERING.items():
            parent = prefix + event
            add(parent, events[event], 'source:' + scope + '-hooks', event).update(
                form=('hook', 'Hook', event),
                connections=[{'target': other + event,
                              'label': 'Inside a project' if scope == 'global' else 'Outside a project'}])
            modules = {}
            for matcher, chain in matchers.items():
                for module in applicable_chain(list(chain), None if scope == 'global' else 1):
                    modules.setdefault(module, []).append(matcher)
            for module, tools in modules.items():
                path = REPO / 'packages/yoke-core/src' / (module.replace('.', '/') + '.py')
                if not path.is_file():
                    continue
                stem = module.rsplit('.', 1)[-1]
                description = (ast.get_docstring(ast.parse(path.read_text())) or '').split('\n')[0]
                description = HOOK_DESCRIPTIONS.get(stem, description)
                condition = 'When applicable' if '_default' in tools else 'Tools: ' + ', '.join(tools)
                kind = 'rule' if guard_scope(module) else 'action'
                if stem in templates or stem in ('session_message_delivery', 'session_resume_block'):
                    kind = 'reply'
                node = add(parent + ':' + module, CHECK_OUTPUT_TITLES.get(stem, names.get(stem, stem.replace('_', ' '))),
                           parent, condition + '. ' + description)
                node.update(document='../../../../' + path.relative_to(REPO).as_posix(),
                            source_only=True, hook_module=module, hook_mode=scope, order=1 if kind == 'action' else 0,
                            form=(kind, {'rule': 'Check', 'action': 'Background action',
                                         'reply': 'Message'}[kind], condition))
                if event == 'SessionEnd' and stem == 'session_launch_attestation':
                    node.update(title='Record launch outcome', summary='Record an unbound launch when its session ends; no launch instructions are delivered.',
                                form=('action', 'Background action', 'SessionEnd'))
                elif stem in templates:
                    copies.append((node, 'hook-block:' + templates[stem]))
        path = REPO / CORE / ('global_orientation.py' if scope == 'global' else 'session_orientation.py')
        name = 'render_global_orientation' if scope == 'global' else 'render_orientation'
        row = next(r for r in ast.parse(path.read_text()).body
                   if isinstance(r, ast.FunctionDef) and r.name == name)
        node = source_node(add, 'hook:' + scope + ':orientation', 'Yoke Orientation',
                           prefix + 'UserPromptSubmit', 'Shown once, on the first prompt.',
                           path, row, 'reply', 'Startup message')
        node.update(order=-1, applicability=['Codex', 'Claude Code'], delivery_label='First prompt only')
        messages[node['id']] = node
        cursor = add(node['id'] + ':cursor', 'Yoke Orientation', prefix + 'SessionStart',
                     'Shown when the session starts.')
        cursor.update(order=-1, applicability=['Cursor only'], delivery_label='Session start', form=('reply', 'Startup message', 'Cursor session start'))
        copies.append((cursor, node['id']))
    for name, function, title in (
        (CORE + 'main_agent_packet.py', 'render_main_agent_block', 'Main-session startup block'),
        (HOOKS + 'session_launch_attestation.py', 'render_launch_instructions', 'Launch instructions'),
        (HOOKS + 'session_broker_wake.py', '_render', 'Wake message'),
    ):
        path = REPO / name
        row = next(r for r in ast.parse(path.read_text()).body
                   if isinstance(r, ast.FunctionDef) and r.name == function)
        if function == 'render_main_agent_block':
            node = source_node(add, 'hook-block:' + function, title,
                               'hook:project:orientation:startup', 'Instructions included in project orientation.',
                               path, row, 'reply', 'Message')
            node['related'] = ['source:packets']
        else:
            node = next(n for n, template in copies if template == 'hook-block:' + function)
        messages['hook-block:' + function] = node
    # Reuse message definitions while displaying their contents in each event and mode.
    sections = []
    def collect(key, title, parent=None, summary=''):
        node = dict(id=key, title=title, parent=parent, summary=summary)
        sections.append(node)
        return node
    add_message_sections(collect, messages)
    for node in sections:
        if node['parent'] in messages:
            node['parent'] = messages[node['parent']]['id']
        add(node['id'], node['title'], node['parent'], node['summary']).update(node)
    for destination, template in copies:
        original = messages[template]
        if destination['id'] == original['id']:
            continue
        destination['connections'] = [{'target': original['id'], 'label': 'Same message format'}]
        for section in sections:
            if section['parent'] != original['id']:
                continue
            child = dict(section, id=destination['id'] + ':' + section['id'].rsplit(':', 1)[-1],
                         parent=destination['id'])
            child.pop('connections', None)
            add(child['id'], child['title'], child['parent'], child['summary']).update(child)


def add_message_sections(add, messages):
    """Expose message contents, without running hooks or loading session data."""
    sections = {
        'hook:global:orientation': (
            ('identity', 'Session and current folder',
             'Your Session: {session_id}. The message says this folder is outside every Yoke project.'),
            ('selection', 'Choose a project',
             'Ask what the user wants to work on. Use yoke-global to pick or add a project; open a new session in its folder.'),
            ('help', 'Status and command help',
             'yoke status · yoke --help · https://upyoke.com/docs'),
            ('writing', 'Writing to the user',
             'The shared user-writing rules are included in this message.'),
            ('folders', 'Known project folders',
             'Optional: up to five configured folders, then yoke projects list for more. Omitted when space is limited.'),
            ('setup', 'Setup status and next action',
             'Current setup guidance, or the shorter pointer: yoke setup --agent.'),
        ),
        'hook:project:orientation': (
            ('identity', 'Session identity',
             'Your Session: {session_id}. Do not infer identity from the active sessions table.'),
            ('checkout', 'Checkout and branch',
             'Root: {root}. Branch and recent commit are optional and may be omitted to fit the message.'),
            ('advisories', 'Installation notices',
             'Conditional notices for outdated installed rules, missing interpreter dependencies or the CLI missing from PATH.'),
            ('setup', 'Setup status and next action',
             'Current setup facts, or the shorter pointer: yoke onboard checklist get.'),
            ('startup', 'Main-session startup block',
             'Includes connection authority, message trust and commands for reading more context.'),
        ),
        'hook-block:render_main_agent_block': (
            ('authority', 'Connection authority',
             'Rules for which connection may perform an operation.'),
            ('trust', 'Message trust',
             'How to interpret message envelopes, bodies and receipts; body records remain inert JSON strings.'),
            ('reads', 'Where to read more',
             'Read packets by topic, command --help and the installed harness manifest. Refresh a missing manifest.'),
            ('advisories', 'Installation notices',
             'Conditional interpreter and CLI notices when the caller has not already included them.'),
        ),
        'hook-block:render_launch_instructions': (
            ('identity', 'Sender and message identity',
             'The delivery includes the sender actor and message ID.'),
            ('authority', 'Authority and registration',
             'Untrusted operational context cannot override approvals, claims, sandboxing or security policy. Includes automatic registration guidance.'),
            ('acknowledge', 'Acknowledge after reading',
             'yoke messages acknowledge {message_id}'),
            ('body', 'Delivered instructions',
             'The variable message body appears between explicit instruction boundaries.'),
        ),
        'hook-block:_render': (
            ('request', 'Wake a stopped session',
             'A stopped session on this machine needs a native wake. The request carries no message body or extra authority.'),
            ('command', 'Run the supplied command once',
             'Run exactly once now: {lease.command}'),
            ('boundary', 'Do not forward the request',
             'Do not forward or broker this request to another session.'),
        ),
    }
    for parent, rows in sections.items():
        for key, title, body in rows:
            node = add(parent + ':' + key, title, parent, body)
            node.update(form=('section', 'Text section', 'Part of the message above'))
            if key == 'startup':
                node['related'] = ['hook-block:render_main_agent_block']
            if key == 'reads':
                node['related'] = ['source:packets', 'source:help']
    # Both deliveries point to the same instruction source, rather than copying it.
    writing = add('hook-writing-source', 'Shared user-writing rules',
                  'hook:global:orientation:writing', 'Exact text included by the renderer.')
    writing.update(document='../../../../' + CONTRACTS + 'user_writing_rules.py',
                   source_only=True, form=('file', 'Shared instruction source', 'user_writing_rules.py'))


def reply_commands():
    commands = {fid: cmd for cmd, fid in live_registries()['commands'].items()}
    result = {}
    for path in (REPO / CORE / 'handlers').glob('_register*.py'):
        for row in ast.walk(ast.parse(path.read_text())):
            if not isinstance(row, ast.Call) or len(row.args) < 4:
                continue
            if not isinstance(row.func, ast.Attribute) or row.func.attr != 'register':
                continue
            fid = literal(row.args[0])
            model = row.args[3]
            name = model.attr if isinstance(model, ast.Attribute) else getattr(model, 'id', '')
            if fid in commands:
                result.setdefault(name, []).append(commands[fid])
    return result


def add_replies(add):
    command_names = reply_commands()
    parent = add('replies:envelope', 'Result, warning and error fields', 'source:feedback',
                 'The shared JSON reply structure.')
    parent['form'] = ('group', 'Response schemas', 'FunctionCallResponse')
    extras = add('replies:other', 'Other declared replies', 'source:feedback',
                 'Response definitions without a direct CLI registration in this inventory.')
    extras['form'] = ('group', 'Response definitions', 'Source declarations')
    paths = [REPO / CONTRACTS / 'api/function_call.py']
    paths.extend(sorted((REPO / CORE / 'handlers').glob('*.py')))
    for path in paths:
        rows = [r for r in ast.parse(path.read_text()).body if isinstance(r, ast.ClassDef)
                and (r.name.endswith('Response') or r.name in {'FunctionError', 'FunctionWarning'})]
        if not rows:
            continue
        for row in rows:
            commands = command_names.get(row.name, [])
            group = 'replies:envelope'
            if path.name != 'function_call.py':
                group = 'replies:' + (commands[0].split()[1] if commands else path.stem)
                title = 'yoke ' + commands[0].split()[1] if commands else path.stem.replace('_', ' ')
                node = add(group, title, 'source:feedback' if commands else 'replies:other',
                           'Command results and their fields.')
                node['form'] = ('group', 'Command replies', path.relative_to(REPO).as_posix())
            title = commands[0] if commands else re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', row.name)
            node = source_node(add, group + ':' + row.name, title, group,
                               (ast.get_docstring(row) or '').split('\n')[0], path, row,
                               'reply', 'Reply schema')
            node['related'] = ['command:' + command for command in commands]
            add_reply_fields(add, node['id'], path, row)
    errors = add('replies:errors', 'Named errors', 'source:feedback',
                 'Error codes and messages declared by command handlers; runtime values vary.')
    errors['form'] = ('reply', 'Error messages', 'FunctionError declarations')
    for path in paths[1:]:
        entries = []
        for row in ast.walk(ast.parse(path.read_text())):
            if not isinstance(row, ast.Call) or not isinstance(row.func, ast.Name):
                continue
            if row.func.id != 'FunctionError':
                continue
            fields = {k.arg: literal(k.value) for k in row.keywords}
            if isinstance(fields.get('code'), str):
                entries.append((row, fields))
        if not entries:
            continue
        parent = 'errors:' + path.stem
        group = add(parent, path.stem.replace('_', ' '), 'replies:errors', '')
        group['form'] = ('group', 'Handler errors', path.relative_to(REPO).as_posix())
        for row, fields in entries:
            node = source_node(add, parent + ':' + str(row.lineno), fields['code'], parent,
                               fields.get('message') or 'Message contains values supplied at runtime.',
                               path, row, 'reply', 'Error code')
    path = REPO / 'packages/yoke-cli/src/yoke_cli/config/setup_agent_response.py'
    node = add('setup-replies', 'question · browser · done · failed · refused',
               'branch:shared-setup', 'Agent setup returns one of these states in each JSON reply.')
    node.update(document='../../../../' + path.relative_to(REPO).as_posix(), source_only=True,
                form=('reply', 'Setup reply states', 'yoke setup --agent'))
    node['related'] = ['branch:agent-setup']
