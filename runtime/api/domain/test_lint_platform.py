"""Portable source ratchet rejects new hits and requires removing fixed entries."""
from pathlib import Path
import json
import subprocess

import pytest
from yoke_core.domain import lint_platform as lint


pytestmark = pytest.mark.windows


@pytest.mark.parametrize(('source', 'rule'), [
    ('import fcntl', 'fcntl'),
    ('from fcntl import flock', 'fcntl'),
    ('import os as host; host.kill(pid, 0)', 'process'),
    ('import subprocess; subprocess.run(["ps", "-ef"])', 'process'),
    ('import os; os.killpg(pid, 15)', 'process'),
    ('import os; os.setsid()', 'process'),
    ('Popen(argv, preexec_fn=prepare)', 'process'),
    ('import os; os.getuid()', 'getuid'),
    ('path.symlink_to(target)', 'symlink'),
    ('Path("/tmp")', 'tmp'),
    ('open(path)', 'encoding'),
    ('path.read_text()', 'encoding'),
    ('path.write_text("hello")', 'encoding'),
])
def test_flags_platform_calls(source, rule):
    assert rule in {hit.rule for hit in lint.scan_source(source, 'client.py')}


@pytest.mark.parametrize('source', [
    'open(path, "rb")', 'open(path, mode="wb")',
    'open(path, encoding="utf-8")', 'path.read_text(encoding="utf-8")',
    'path.write_text("hi", encoding="utf-8")', 'import os; os.open(path, flags)',
    'import os\nif hasattr(os, "getuid"):\n os.getuid()',
    'import os\nif os.name != "nt":\n os.getuid()',
])
def test_portable_calls_pass(source):
    assert not lint.scan_source(source, 'client.py')


def test_guard_does_not_exempt_wrong_branch_or_later_call():
    source = 'import os\nif hasattr(os, "getuid"):\n pass\nelse:\n os.getuid()\nos.getuid()'
    assert len(lint.scan_source(source, 'client.py')) == 2


def test_fingerprints_survive_line_movement_but_not_changed_call():
    original = lint.scan_source('os.kill(pid, 0)', 'client.py')[0]
    assert lint.scan_source('\n\nos.kill(pid, 0)', 'client.py')[0].key == original.key
    assert lint.scan_source('os.kill(other, 0)', 'client.py')[0].key != original.key


def test_repository_platform_ratchet():
    root = Path(__file__).resolve().parents[3]
    assert lint.ratchet_findings(root) == []


def test_allowance_list_can_only_shrink():
    root = Path(__file__).resolve().parents[3]
    assert lint.baseline_growth(root) == []


def _git(root, *args):
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)


def _commit_baseline(root, grouped, message):
    path = root / lint.BASELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grouped), encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', message)


def test_growth_compares_to_merge_base_not_moving_main(tmp_path):
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _commit_baseline(tmp_path, {'a.py': {'tmp|x': 2, 'process|y': 1}}, 'base')
    _git(tmp_path, 'checkout', '-qb', 'candidate')
    _git(tmp_path, 'checkout', '-q', 'main')
    _commit_baseline(tmp_path, {'a.py': {'tmp|x': 1}}, 'main prunes entries')
    _git(tmp_path, 'update-ref', 'refs/remotes/origin/main', 'main')
    _git(tmp_path, 'checkout', '-q', 'candidate')
    assert lint.baseline_growth(tmp_path) == []
    _commit_baseline(tmp_path, {'a.py': {'tmp|x': 3, 'process|y': 1, 'symlink|z': 1}}, 'grow')
    growth = lint.baseline_growth(tmp_path)
    assert [line.split(' (')[0] for line in growth] == [
        'grown_platform_allowance: a.py|symlink|z', 'grown_platform_allowance: a.py|tmp|x']


def test_growth_fails_loudly_without_integration_ref(tmp_path):
    _git(tmp_path, 'init', '-q', '-b', 'main')
    _commit_baseline(tmp_path, {}, 'base')
    with pytest.raises(lint.BaselineBaseUnavailable, match='git fetch origin main'):
        lint.baseline_growth(tmp_path)


def test_prune_only_reduces_known_sites(monkeypatch, tmp_path):
    baseline_path = tmp_path / lint.BASELINE
    baseline_path.parent.mkdir(parents=True)
    known = lint.PlatformHit('client.py', 1, 'process', 'known')
    new = lint.PlatformHit('client.py', 2, 'process', 'new')
    from collections import Counter
    lint._write_baseline(baseline_path, Counter({known.key: 2, 'gone.py|tmp|old': 1}))
    monkeypatch.setattr(lint, 'scan_tree', lambda root: [known, new])
    findings = lint.ratchet_findings(tmp_path, prune=True)
    assert lint.read_baseline(baseline_path) == {known.key: 1}
    assert len(findings) == 1 and 'new_platform_offender' in findings[0]
    assert new.key in findings[0]


def test_fingerprints_ignore_optional_empty_fields_across_python_versions():
    import ast
    node = ast.parse('open(path)').body[0].value
    expected = lint.fingerprint(node)
    # Older Python dumps []/None; newer Python omits them by default.
    del node.keywords
    assert lint.fingerprint(node) == expected
    literal = ast.Constant(value='hello', kind=None)
    expected = lint.fingerprint(literal)
    del literal.kind
    assert lint.fingerprint(literal) == expected


def test_scope_includes_public_installer_and_excludes_server_image(tmp_path):
    client = tmp_path / 'packaging/public-installer/install.py'
    server = tmp_path / 'packages/yoke-core/src/yoke_core/api/server.py'
    for path in (client, server):
        path.parent.mkdir(parents=True)
        path.write_text('open(path)', encoding='utf-8')
    assert [hit.path for hit in lint.scan_tree(tmp_path)] == [client.relative_to(tmp_path).as_posix()]
