"""Read setup prompts and packet definitions without running setup or fetching state."""

import ast
from explorer_documents import REPO

CLI = 'packages/yoke-cli/src/yoke_cli/config/'
CORE = 'packages/yoke-core/src/yoke_core/domain/'


def assignments(path):
    result = {}
    for row in ast.parse(path.read_text()).body:
        if isinstance(row, ast.Assign) and isinstance(row.targets[0], ast.Name):
            result[row.targets[0].id] = row.value
        elif isinstance(row, ast.AnnAssign) and isinstance(row.target, ast.Name):
            result[row.target.id] = row.value
    return result


def literal(row, names=None, depth=0):
    if row is None or depth > 5:
        return None
    if isinstance(row, ast.Name) and names and row.id in names:
        return literal(names[row.id], names, depth + 1)
    try:
        return ast.literal_eval(row)
    except (ValueError, TypeError):
        return None


def source_node(add, key, title, parent, summary, path, row, kind, label):
    node = add(key, title, parent, summary)
    relative = path.relative_to(REPO).as_posix()
    node.update(document='../../../' + relative,
                document_lines=[row.lineno - 1, row.end_lineno], source_only=True,
                form=(kind, label, relative + ':' + str(row.lineno)))
    return node


def add_setup(add):
    installer = add('installer:script', 'Install Yoke', 'source:setup',
                    'upyoke.com/install · installs the CLI and starts setup unless skipped.')
    installer.update(document='../../../packaging/public-installer/install', source_only=True,
                     form=('command', 'Install script', 'curl -fsSL https://upyoke.com/install | sh'),
                     related=['branch:install-command', 'branch:agent-setup', 'branch:terminal-setup'])
    step_order = [literal(value) for value in assignments(REPO / CLI / 'onboard_wizard_step_ids.py').values()]
    files = sorted((REPO / CLI).glob('*.py'))
    common = {}
    for path in files:
        common.update(assignments(path))
    for path in files:
        code = ast.parse(path.read_text())
        names = common | assignments(path)
        for row in ast.walk(code):
            if not isinstance(row, ast.Call) or not isinstance(row.func, ast.Name):
                continue
            if row.func.id != 'SetupPrompt':
                continue
            fields = {k.arg: k.value for k in row.keywords}
            key = literal(fields.get('key'), names)
            title = literal(fields.get('title'), names)
            if not key and not title:
                continue  # Shared render helpers have no specific question of their own.
            identity = path.stem + ':' + str(row.lineno)
            step = literal(fields.get('step'), names) or 'Other setup questions'
            for branch, kind, label in (
                ('agent-setup', 'reply', 'Setup question'),
                ('terminal-setup', 'screen', 'Setup screen'),
            ):
                parent = 'setup-step:' + branch + ':' + str(step)
                # Group ids are deduplicated by the caller after inventory collection.
                group = add(parent, str(step).replace('_', ' ').title(), 'branch:' + branch, '')
                group['form'] = ('group', 'Setup step', str(step))
                group['order'] = step_order.index(step) if step in step_order else len(step_order)
                node = source_node(add, 'prompt:' + branch + ':' + identity,
                                   title or str(key), parent, str(key or ''), path, row, kind, label)
                details = []
                for field in ('subtitle', 'message', 'guidance'):
                    value = literal(fields.get(field), names)
                    if isinstance(value, str) and value:
                        details.append(value)
                node['body'] = '\n\n'.join(details)
                other = 'terminal-setup' if branch == 'agent-setup' else 'agent-setup'
                node['related'] = ['prompt:' + other + ':' + identity]
                choices = fields.get('choices')
                if isinstance(choices, ast.Name):
                    choices = names.get(choices.id)
                if isinstance(choices, (ast.Tuple, ast.List)):
                    for index, choice in enumerate(choices.elts):
                        if not isinstance(choice, ast.Call):
                            continue
                        values = [literal(arg, names) for arg in choice.args]
                        kwargs = {k.arg: literal(k.value, names) for k in choice.keywords}
                        value = kwargs.get('value') or (values[0] if values else None)
                        label_text = kwargs.get('label') or (values[1] if len(values) > 1 else value)
                        hint = kwargs.get('hint') or (values[2] if len(values) > 2 else '')
                        if label_text:
                            child = add(node['id'] + ':choice:' + str(index), str(label_text),
                                        node['id'], str(hint or ''))
                            child.update(body=str(value), form=('prompt', 'Answer choice', str(value)))


def add_packets(add):
    table_sources = {}
    for source in (REPO / CORE).glob('schema_api_context_table*.py'):
        for row in ast.walk(ast.parse(source.read_text())):
            if isinstance(row, ast.Dict):
                for key, value in zip(row.keys, row.values):
                    name = literal(key)
                    if isinstance(name, str) and isinstance(value, ast.Dict):
                        fields = {literal(k): v for k, v in zip(value.keys, value.values)}
                        if 'columns' in fields:
                            table_sources[name] = source, value, fields['columns']
    path = REPO / CORE / 'schema_api_context_seed.py'
    names = assignments(path)
    roles = literal(names['ROLE_TOPICS'])
    tables = literal(names['TOPIC_TABLES'])
    for role, topics in roles.items():
        node = add('packet:' + role, role, 'source:packets',
                   'yoke packets render --role ' + role)
        node['form'] = ('packet', 'Role packet', node['summary'])
        node['related'] = ['command:yoke packets render']
        for topic in topics:
            key = node['id'] + ':' + topic
            child = add(key, topic, node['id'], 'Tables and commands in the ' + topic + ' packet.')
            child['form'] = ('packet', 'Packet topic', node['summary'] + ' --topic ' + topic)
            for table in tables.get(topic, ()):
                leaf = add(key + ':' + table, table, key, 'Schema reference included in this topic.')
                leaf['form'] = ('packet', 'Table reference', child['form'][2])
                leaf['related'] = ['command:yoke packets render']
                if table in table_sources:
                    source, row, columns = table_sources[table]
                    leaf.update(document='../../../' + source.relative_to(REPO).as_posix(),
                                document_lines=[row.lineno - 1, row.end_lineno], source_only=True)
                    if isinstance(columns, (ast.List, ast.Tuple)):
                        values = [literal(column) for column in columns.elts]
                        leaf['body'] = '\n'.join(f'{value[0]} · {value[1]}' for value in values
                                                 if isinstance(value, (tuple, list)) and len(value) == 2)

    path = REPO / CORE / 'shipped_execution_instruction.py'
    value = literal(assignments(path)['SHIPPED_EXECUTION_INSTRUCTION'])
    node = add('instruction:shipped', 'Built-in execution instructions', 'source:instructions',
               'The instruction text seeded into new Yoke universes.')
    node.update(body=value, form=('rule', 'Instruction text', path.relative_to(REPO).as_posix()))
    for index, paragraph in enumerate(value.split('\n- ')):
        title = paragraph.removeprefix('- ').split('. ')[0].rstrip('.')
        child = add('instruction:shipped:' + str(index), title, node['id'], '')
        child.update(body=paragraph.removeprefix('- '), form=('rule', 'Instruction clause', 'Built-in execution instructions'))
    node = add('instruction:resolve', 'yoke workflow execution-instruction resolve',
               'source:instructions', 'Reads the actual instructions for a workflow and project.')
    node.update(form=('command', 'Read scoped rules', 'Content depends on the selected workflow and project'),
                related=['command:yoke workflow execution-instruction resolve',
                         'doc:docs/public/projects/execution-instructions.md'])


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



HOOK_DESCRIPTIONS = {
    'session_dispatch': 'Keeps the session registration and lifecycle state up to date.',
    'session_resume_block': 'If a paused session resumes, show its pending resume notice once.',
    'session_message_delivery': 'If messages are waiting, deliver them when this harness can show them to the agent.',
    'session_launch_attestation': 'If this session was launched with instructions, show the sender, instructions and acknowledgement command.',
    'session_broker_wake': 'If another session needs waking, supply one command to run once; do not forward the request.',
    'heartbeat': 'Records that this session is still active. Usually adds no message.',
    'observe_pre': 'Records the tool activity for Yoke. Usually adds no message.',
    'observe': 'Records the tool result for Yoke. Usually adds no message.',
}


def add_delivery_topics(nodes):
    """Describe the prose delivered, independently of the delivery implementation."""
    topics = {
        'session_message_delivery': (
            ('Delivery boundaries', 'Start and end markers identify this delivery and its message.'),
            ('Sender', 'Who sent the message, including the actor and session or surface.'),
            ('Message body', 'The message text, quoted line by line. Actual length varies with the sender’s content.'),
            ('Reminder', 'If already shown: how many times, and whether to act or acknowledge it.'),
            ('Read the full message', 'Long reminders show up to 400 body characters, with a yoke messages get command.'),
            ('Acknowledge', 'A yoke messages acknowledge command for the delivered message.'),
            ('More waiting messages', 'If messages do not fit, show the remaining count and commands to list and read them.'),
        ),
        'session_resume_block': (
            ('Session resumed', 'Explains that the session ended and has now reactivated.'),
            ('Previous work claims', 'Lists the work claims recorded when the session reactivated.'),
            ('Reclaimed or conflicting work', 'Shows counts of automatically reacquired claims and conflicts, when present.'),
            ('Resume work', 'Offers /yoke charge to select work and yoke claims work acquire to claim it explicitly.'),
        ),
    }
    for node in list(nodes):
        module = node.get('hook_module', '').rsplit('.', 1)[-1]
        if module not in topics:
            continue
        node['message_estimate'] = dict(label='Output · variable lines and bytes',
            assumptions='Depends on message bodies and waiting messages.' if module == 'session_message_delivery'
            else 'Depends on previous work claims and their outcomes.')
        for index, (title, prose) in enumerate(topics[module]):
            nodes.append(dict(id=node['id'] + ':text:' + str(index), parent=node['id'],
                              title=title, summary=prose, form=('section', 'Text section', 'Delivered message content')))


CHECK_OUTPUT_TITLES = {
    'lint_shell_backtick_search': 'Quote search text so backticks cannot execute',
    'lint_local_privacy': 'This command crosses a private-data boundary',
    'lint_unmatched_path_glob': 'Fix the file pattern or search option',
    'lint_db_cmd': 'Use the supported database or session command',
    'lint_main_commit': 'Commit implementation work in your worktree',
    'lint_tc_label': 'Use descriptive test names and labels',
    'lint_long_command_polling': 'Use the watcher instead of repeatedly polling',
    'lint_pipe_to_truncator': 'Do not truncate a running command’s output',
    'lint_raw_pytest_full_suite': 'Run the full test suite through the watcher',
    'lint_watcher_module_form': 'Use the current watcher command',
    'lint_headless_watcher_timeout': 'Set the required watcher timeout',
    'lint_if_status_capture': 'Capture the failed command’s actual exit status',
    'lint_subagent_background': 'Subagents must finish within their own turn',
    'lint_subagent_fleet_messaging': 'Leave fleet message changes to the parent agent',
    'lint_session_cwd': 'Use the folder authorized for this session',
    'lint_lane_main_write': 'Write implementation files in your claimed worktree',
    'lint_workspace_cwd_match': 'Run this write from the correct checkout',
    'path_claim_bash_guard': 'This file change needs the correct path claim',
    'lint_structured_field_transform_shell': 'Use the supported structured-field update',
    'lint_shell_quoted_function_payload': 'Pass structured data without hand-quoting shell payloads',
    'lint_yoke_adapter_stderr_visibility': 'Keep diagnostic errors visible',
    'lint_yoke_quoted_shell_substitution': 'Prevent shell substitution inside Yoke arguments',
    'lint_no_agent_runtime_api_import_from_c': 'Use the Yoke CLI instead of importing its runtime',
    'lint_no_agent_curl_against_yoke_api': 'Use the Yoke CLI instead of curl',
    'lint_no_agent_session_end': 'Release work claims; let the harness end the session',
    'lint_claim_ownership_mutations': 'Do not bypass another session’s work claim',
    'lint_git_stash_arg_order': 'Put the stash message flag before the path separator',
    'lint_destructive_git': 'Protect uncommitted work before destructive Git operations',
    'path_claim_pre_edit_guard': 'This edit needs the correct path claim',
    'lint_write_path': 'Fix literal shell variables or unsupported secret references',
    'lint_python_runtime_import_in_tmp': 'Use a supported command instead of a temporary runtime script',
    'hint_file_line_limit_approach': 'This file is approaching the line limit',
    'lint_monitor_watcher_tail': 'Use the watcher’s completion-aware monitor command',
    'db_error_hook': 'Investigate the database error or unexpected write result',
    'turn_end_promised_work_gate': 'Finish pending work or deliberately park before stopping',
}
