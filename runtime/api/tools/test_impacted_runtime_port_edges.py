"""Provider source changes retain consumers of runtime interfaces."""

import importlib.metadata

import pytest

from yoke_core.tools._impacted_import_index import build_import_index, reachable_tests
from yoke_core.tools.impacted_tests import select

PREFIX = 'packages/yoke-cli/src/yoke_cli/'
CONSUMER = 'runtime/api/test_consumer.py'
OTHER = 'runtime/api/test_other.py'


def _write(root, path, body):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    # Source scanning must not load another checkout's installed entry points.
    monkeypatch.setattr(importlib.metadata, 'entry_points', lambda **kw: pytest.fail('installed metadata read'))
    _write(tmp_path, 'packages/yoke-cli/pyproject.toml', '''
[project.entry-points."yoke.runtime"]
git = "yoke_cli.provider"
other = "yoke_cli.other"
''')
    for port in ('git', 'other'):
        _write(tmp_path, f'packages/yoke-contracts/src/yoke_contracts/runtime_ports/{port}.py', f'''
def get():
    return load_port("{port}", Interface)
''')
    _write(tmp_path, PREFIX + 'helper.py', 'VALUE = 1\n')
    _write(tmp_path, PREFIX + 'provider.py', 'from yoke_cli.helper import VALUE\n')
    _write(tmp_path, PREFIX + 'other.py', 'VALUE = 2\n')
    _write(tmp_path, 'packages/yoke-core/src/yoke_core/domain/consumer.py', '''
from yoke_contracts.runtime_ports.git import get
provider = get()
''')
    _write(tmp_path, CONSUMER, 'from yoke_core.domain.consumer import provider\n')
    _write(tmp_path, OTHER, 'from yoke_contracts.runtime_ports.other import get\n')
    for n in range(20):
        _write(tmp_path, f'runtime/api/test_unrelated_{n}.py', 'def test_ok(): pass\n')
    return tmp_path


@pytest.mark.parametrize('changed', ['provider.py', 'helper.py'])
def test_provider_and_helper_reach_only_their_interface_consumers(checkout, changed):
    index = build_import_index(checkout)
    reached = reachable_tests([PREFIX + changed], index)
    assert reached == {CONSUMER}
    selection = select([PREFIX + changed], index, bounded=True)
    assert CONSUMER in selection.files
    assert OTHER not in selection.files


def test_declared_deleted_provider_still_reaches_consumers(checkout):
    (checkout / (PREFIX + 'provider.py')).unlink()
    assert reachable_tests([PREFIX + 'provider.py'], build_import_index(checkout)) == {CONSUMER}
