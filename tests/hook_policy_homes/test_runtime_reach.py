"""Runtime interfaces retain precise source-level hook reachability."""

import pytest

from tests.hook_policy_homes import reach as scanner
from tests.hook_policy_homes.runtime_providers import providers


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    def write(relative, text):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    write('packages/adapter/pyproject.toml', '''
[project.entry-points."yoke.runtime"]
git = "yoke_cli.provider"
''')
    write('src/yoke_contracts/runtime_ports/git.py', '''
def get_git():
    return load_port("git", Git)
''')
    write('src/yoke_cli/provider.py', '''
from yoke_cli.actual import run

def unrelated():
    return open("unrelated")
''')
    write('src/yoke_cli/actual.py', '''
def run():
    return open("used")
''')
    monkeypatch.setattr(scanner, 'REPO', tmp_path)
    monkeypatch.setattr(scanner, '_PACKAGE_ROOTS', {
        name: tmp_path / 'src' for name in ('yoke_core', 'yoke_cli', 'yoke_contracts')
    })
    scanner._module.cache_clear()
    yield write
    scanner._module.cache_clear()
    providers.cache_clear()


@pytest.mark.parametrize('source', [
    '''from yoke_contracts.runtime_ports.git import get_git
git = get_git()
def evaluate():
    git.run()
''',
    '''from yoke_contracts.runtime_ports.git import get_git as acquire
def evaluate():
    renamed = acquire()
    renamed.run()
''',
    '''from yoke_contracts.runtime_ports.git import get_git
def evaluate():
    get_git().run()
''',
])
def test_runtime_provider_members_and_reexports_are_reached(source_tree, source):
    source_tree('src/yoke_core/policy.py', source)
    reached = scanner.reach([('yoke_core.policy', 'evaluate')])
    assert ('yoke_cli.actual', 'run') in reached
    assert ('yoke_cli.provider', 'unrelated') not in reached
    assert any(read.key == 'yoke_cli.actual:run' for read in scanner.local_reads(reached))


@pytest.mark.parametrize('declaration', [
    '',
    '[project.entry-points."yoke.runtime"]\ngit = "yoke_cli.missing"',
    '[project.entry-points."yoke.runtime"]\ngit = "yoke_cli.provider:run"',
])
def test_invalid_provider_is_visible(source_tree, declaration):
    source_tree('packages/adapter/pyproject.toml', declaration)
    source_tree('src/yoke_core/policy.py', '''
from yoke_contracts.runtime_ports.git import get_git
def evaluate():
    get_git().run()
''')
    with pytest.raises(ValueError, match='provider'):
        scanner.reach([('yoke_core.policy', 'evaluate')])


def test_duplicate_provider_is_visible(source_tree):
    source_tree('packages/other/pyproject.toml', '''
[project.entry-points."yoke.runtime"]
git = "yoke_cli.provider"
''')
    with pytest.raises(ValueError, match='duplicate'):
        providers(scanner.REPO)
