"""Coverage is proved against collection, never inferred from green shards."""

import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from yoke_core.tools import ci_shard_coverage as coverage


def _report(path, cases):
    document = ET.Element('testsuite')
    for classname, name in cases:
        ET.SubElement(document, 'testcase', classname=classname, name=name)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(document).write(path)
    return path


def test_complete_reports_include_skipped_tests(tmp_path):
    path = _report(tmp_path / 'report.xml', [('tests.test_a', 'test_a')])
    tree = ET.parse(path)
    ET.SubElement(tree.find('testcase'), 'skipped')
    tree.write(path)
    assert coverage.compare([['tests.test_a', 'test_a', 'tests/test_a.py::test_a']],
                            [path], '3.11')['tests'] == 1


def test_missing_duplicate_and_unexpected_ids_are_named(tmp_path):
    expected = [['tests.test_a', name, f'tests/test_a.py::{name}']
                for name in ('test_present', 'test_missing')]
    path = _report(tmp_path / 'report.xml', [('tests.test_a', 'test_present')] * 2
                   + [('tests.test_a', 'test_extra')])
    with pytest.raises(ValueError) as error:
        coverage.compare(expected, [path], '3.14')
    message = str(error.value)
    assert 'Python 3.14' in message
    assert 'tests/test_a.py::test_missing' in message
    assert 'tests/test_a.py::test_present (2 times)' in message
    assert 'tests.test_a::test_extra' in message


def test_missing_report_names_the_shard(tmp_path, capsys):
    _report(tmp_path / 'pytest-output-3.11-1' / 'pytest-report.xml', [('a', 'b')])
    assert coverage.main(['--reports', str(tmp_path), '--python', '3.11',
                          '--shards', '2']) == 1
    message = capsys.readouterr().out
    assert 'ci_shard_reports_missing: pytest-output-3.11-2' in message
    assert 'Recovery:' in message


@pytest.mark.parametrize('records', [[], [['a', 'b', 'first'], ['a', 'b', 'second']]])
def test_empty_or_ambiguous_collection_is_refused(records):
    with pytest.raises(ValueError, match='ci_shard_collection_invalid'):
        coverage.compare(records, [], '3.14')


def test_empty_and_malformed_reports_refuse(tmp_path):
    path = _report(tmp_path / 'empty.xml', [])
    with pytest.raises(ValueError, match='ci_shard_report_empty'):
        coverage.compare([['a', 'b', 'a.py::b']], [path], '3.14')
    path.write_text('<broken')
    with pytest.raises(ET.ParseError):
        coverage.compare([['a', 'b', 'a.py::b']], [path], '3.14')


def test_collection_manifest_keeps_parameter_and_class_identity(tmp_path, monkeypatch):
    destination = tmp_path / 'expected.json'
    monkeypatch.setenv(coverage.MANIFEST_ENV, str(destination))
    session = SimpleNamespace(items=[SimpleNamespace(
        nodeid='tests/test_a.py::TestGroup::test_case[a.b::c]')])
    coverage.pytest_collection_finish(session)
    assert json.loads(destination.read_text()) == [[
        'tests.test_a.TestGroup', 'test_case[a.b::c]',
        'tests/test_a.py::TestGroup::test_case[a.b::c]']]


def test_failed_collection_names_its_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage.subprocess, 'run',
                        lambda *a, **kw: SimpleNamespace(returncode=2))
    with pytest.raises(ValueError, match='collection-output.txt'):
        coverage.collect(tmp_path / 'manifest.json')


def test_saved_manifest_replay(tmp_path, capsys):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([['a', 'b', 'a.py::b']]))
    _report(tmp_path / 'pytest-output-3.14-1' / 'pytest-report.xml', [('a', 'b')])
    assert coverage.main(['--reports', str(tmp_path), '--python', '3.14',
                          '--shards', '1', '--expected', str(manifest)]) == 0
    assert 'ci_shard_coverage_passed' in capsys.readouterr().out


def test_retained_clean_and_divergent_report_replay(tmp_path):
    evidence = json.loads((Path(__file__).parent / 'fixtures' /
                           'ci_shard_reports.json').read_text())
    expected = [[row['classname'], row['name'], row['nodeid']]
                for row in evidence['expected']]
    for outcome in ('good', 'bad'):
        reports = []
        for shard, snippets in evidence[outcome].items():
            path = tmp_path / outcome / shard / 'pytest-report.xml'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('<testsuite>' + ''.join(snippets) + '</testsuite>')
            reports.append(path)
        if outcome == 'good':
            assert coverage.compare(expected, reports, '3.14')['tests'] == 5
        else:
            with pytest.raises(ValueError) as error:
                coverage.compare(expected, reports, '3.14')
            for nodeid in evidence['selected']['missing']:
                assert nodeid in str(error.value)
            for nodeid in evidence['selected']['duplicate']:
                assert nodeid + ' (2 times)' in str(error.value)
