"""Named hook deliveries and concrete reply schemas, linked to their definitions."""

import ast
import re
from inventory import live_registries
from explorer_documents import REPO
from explorer_runtime import CORE, source_node, literal

CONTRACTS = 'packages/yoke-contracts/src/yoke_contracts/'
HOOKS = 'packages/yoke-core/src/yoke_core/hooks/'


def add_hooks(add):
    from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING

    messages = {}
    for scope in ('global', 'project'):
        path = REPO / CORE / ('global_orientation.py' if scope == 'global' else 'session_orientation.py')
        name = 'render_global_orientation' if scope == 'global' else 'render_orientation'
        row = next(r for r in ast.parse(path.read_text()).body
                   if isinstance(r, ast.FunctionDef) and r.name == name)
        node = source_node(add, 'hook:' + scope + ':orientation', 'Yoke Orientation',
                           'source:' + scope + '-hooks',
                           'First prompt in Claude/Codex; session start in Cursor.',
                           path, row, 'hook', 'Startup message')
        messages[node['id']] = node
        node['body'] = ('Session identity, current folder, project selection and writing rules.'
                        if scope == 'global' else
                        'Session identity, checkout, setup facts and the main-session startup block.')
    add('shared-hook-events', 'Shared hook event chains', 'source:project-hooks',
        'One registry used inside and outside projects; each handler checks applicability.').update(
            form=('group', 'Shared definitions', 'Global and project hooks'),
            related=['hook-global-events'])
    for event, matchers in HOOK_ORDERING.items():
        parent = 'hook-event:' + event
        node = add(parent, event, 'shared-hook-events',
                   'Registered hook event; applicability depends on harness, tool and scope.')
        node['form'] = ('hook', 'Hook event', event)
        for matcher, modules in matchers.items():
            key = parent + ':' + matcher
            node = add(key, 'All matching tools' if matcher == '_default' else matcher,
                       parent, 'Checks and deliveries in their registered order.')
            node['form'] = ('group', 'Tool matcher', event + ' · ' + matcher)
            for module in modules:
                path = REPO / 'packages/yoke-core/src' / (module.replace('.', '/') + '.py')
                if not path.is_file():
                    continue
                title = module.rsplit('.', 1)[-1].replace('_', ' ')
                tree = ast.parse(path.read_text())
                summary = (ast.get_docstring(tree) or '').split('\n')[0]
                child = add(key + ':' + module, title, key, summary)
                child.update(document='../../../../' + path.relative_to(REPO).as_posix(),
                             source_only=True, form=('hook', 'Hook handler', module))
    # Explicit context blocks are easier to recognize than the handler filenames.
    blocks = (
        (CORE + 'main_agent_packet.py', 'render_main_agent_block', 'Main-session startup block'),
        (HOOKS + 'session_launch_attestation.py', 'render_launch_instructions', 'Launch instructions'),
        (HOOKS + 'session_broker_wake.py', '_render', 'Wake message'),
    )
    for name, function, title in blocks:
        path = REPO / name
        row = next(r for r in ast.parse(path.read_text()).body
                   if isinstance(r, ast.FunctionDef) and r.name == function)
        node = source_node(add, 'hook-block:' + function, title, 'source:project-hooks',
                           (ast.get_docstring(row) or '').split('\n')[0], path, row,
                           'hook', 'Context block')
        messages[node['id']] = node
        if function == 'render_main_agent_block':
            node['related'] = ['source:packets']
    add_message_sections(add, messages)
    add('hook-global-events', 'Shared hook event chains', 'source:global-hooks',
        'The shared runner uses the same registered event chains; checks apply according to scope.').update(
            related=['shared-hook-events'],
            connections=[{'target': 'shared-hook-events', 'label': 'Same event registry'}],
            form=('hook', 'Shared event chains', 'Machine and project applicability is checked at runtime'))

    for event in HOOK_ORDERING:
        add('hook-event-reference:' + event, event, 'hook-global-events',
            'Same registered chain as project hooks; not every handler applies outside a project.').update(
                form=('hook', 'Shared event reference', event),
                related=['hook-event:' + event],
                connections=[{'target': 'hook-event:' + event, 'label': 'Shared definition'}])


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
            source = messages[parent]
            node = add(parent + ':' + key, title, parent, body)
            node.update(body=body,
                        connections=[{'target': source['id'], 'label': 'Contained in message'}],
                        form=('hook', 'Message section', 'From the delivered message'))
            if key == 'startup':
                node['related'] = ['hook-block:render_main_agent_block']
            if key == 'reads':
                node['related'] = ['source:packets', 'source:help']
    # Both deliveries point to the same instruction source, rather than copying it.
    writing = add('hook-writing-source', 'Shared user-writing rules',
                  'hook:global:orientation:writing', 'Exact text included by the renderer.')
    writing.update(document='../../../../' + CONTRACTS + 'user_writing_rules.py',
                   source_only=True, form=('file', 'Shared instruction source', 'user_writing_rules.py'))


def add_reply_fields(add, parent, path, row):
    for field in row.body:
        if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
            continue
        name = field.target.id
        description = ''
        if isinstance(field.value, ast.Call):
            description = next((literal(k.value) for k in field.value.keywords
                                if k.arg == 'description'), '') or ''
        node = add(parent + ':' + name, name, parent, description)
        node['form'] = ('reply', 'Reply field', ast.unparse(field.annotation))


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
