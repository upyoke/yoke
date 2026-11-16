"""Portable source ratchet rejects new hits and requires removing fixed entries."""
from pathlib import Path
import json
import subprocess

import pytest
from yoke_core.domain import lint_platform as lint


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
    # The founding addition has no old file. Once present on main, no entry or
    # count may grow, even if someone changes the baseline alongside bad code.
    old = subprocess.run(['git', 'show', f'origin/main:{lint.BASELINE}'], cwd=root,
                         capture_output=True, text=True, encoding='utf-8')
    if old.returncode:
        return
    previous = {f"{path}|{site}": count for path, sites in json.loads(old.stdout).items()
                for site, count in sites.items()}
    current = lint.read_baseline(root / lint.BASELINE)
    assert all(count <= previous.get(key, 0) for key, count in current.items())


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
