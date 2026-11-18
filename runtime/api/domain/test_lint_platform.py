"""Portable source ratchet rejects new hits and requires removing fixed entries."""
from pathlib import Path

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
    ('open(path, "r")', 'encoding'),
    ('path.open()', 'encoding'),
    ('path.open("r")', 'encoding'),
    ('path.read_text()', 'encoding'),
    ('path.write_text("hello")', 'encoding'),
])
def test_flags_platform_calls(source, rule):
    assert rule in {hit.rule for hit in lint.scan_source(source, 'client.py')}


@pytest.mark.parametrize('source', [
    'open(path, "rb")', 'open(path, mode="wb")',
    'path.open("rb")', 'Path(x).open("a+b")', 'import gzip; gzip.open(f, "rb")',
    'open(path, encoding="utf-8")', 'path.read_text(encoding="utf-8")',
    'path.write_text("hi", encoding="utf-8")', 'import os; os.open(path, flags)',
    'import os\nif hasattr(os, "getuid"):\n os.getuid()',
    'import os\nif os.name != "nt":\n os.getuid()',
])
def test_portable_calls_pass(source):
    assert not lint.scan_source(source, 'client.py')


@pytest.mark.parametrize('source', [
    'import tarfile as archive; archive.open(path)',
    'from PIL import Image as decoder; decoder.open(path)',
    'import webbrowser; webbrowser.open(url)',
    'from urllib.request import build_opener as build; client = build(); client.open(url)',
    'from importlib.metadata import distribution; dist = distribution("pkg"); dist.read_text("RECORD")',
    'from importlib.metadata import Distribution\ndef owning() -> Distribution: ...\ndist = owning(); dist.read_text("RECORD")',
    'from PIL import Image\ndef decoder(): return Image\nimage = decoder(); image.open(path)',
    'class LinuxTerminal:\n def open(self, command): pass\nt = LinuxTerminal(); t.open(command)',
    'from yoke_contracts.runtime_ports.ssh_linux_terminal import get_ssh_linux_terminal\n'
    'Terminal = get_ssh_linux_terminal().LinuxTerminal\nt = Terminal(); t.open(command)',
    'from yoke_cli.config.onboard_checklist_files import write_text as write; write(path, text)',
])
def test_non_text_file_apis_need_no_encoding(source):
    assert not lint.scan_source(source, 'client.py')


@pytest.mark.parametrize('source', [
    'from pathlib import Path\nopener = Path("document"); opener.open()',
    'from urllib.request import build_opener\nclient = build_opener()\nclient = Path("x")\nclient.open()',
    'from importlib.resources import files\nfiles("pkg").joinpath("doc").read_text()',
])
def test_file_calls_remain_checked_despite_non_file_api_names(source):
    assert any(hit.rule == 'encoding' for hit in lint.scan_source(source, 'client.py'))


def test_guard_does_not_exempt_wrong_branch_or_later_call():
    source = 'import os\nif hasattr(os, "getuid"):\n pass\nelse:\n os.getuid()\nos.getuid()'
    assert len(lint.scan_source(source, 'client.py')) == 2


def test_repository_has_no_platform_offenders():
    root = Path(__file__).resolve().parents[3]
    assert lint.findings(root) == []


def test_findings_report_location_rule_and_recovery(tmp_path):
    path = tmp_path / "packaging/public-installer/install.py"
    path.parent.mkdir(parents=True)
    path.write_text("\nopen(path)\n", encoding="utf-8")

    assert lint.findings(tmp_path) == [
        "platform_offender: packaging/public-installer/install.py:2 encoding; "
        "Use the shared platform_* helper or explicit UTF-8 encoding."
    ]


def test_scope_includes_public_installer_and_excludes_server_image(tmp_path):
    client = tmp_path / 'packaging/public-installer/install.py'
    server = tmp_path / 'packages/yoke-core/src/yoke_core/api/server.py'
    for path in (client, server):
        path.parent.mkdir(parents=True)
        path.write_text('open(path)', encoding='utf-8')
    assert [hit.path for hit in lint.scan_tree(tmp_path)] == [client.relative_to(tmp_path).as_posix()]
