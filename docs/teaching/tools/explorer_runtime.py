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
    node.update(document='../../../../' + relative,
                document_lines=[row.lineno - 1, row.end_lineno], source_only=True,
                form=(kind, label, relative + ':' + str(row.lineno)))
    return node


def add_setup(add):
    installer = add('installer:script', 'Install Yoke', 'source:setup',
                    'upyoke.com/install · installs the CLI and starts setup unless skipped.')
    installer.update(document='../../../../packaging/public-installer/install', source_only=True,
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
                    leaf.update(document='../../../../' + source.relative_to(REPO).as_posix(),
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
