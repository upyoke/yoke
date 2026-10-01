"""Lease-local OS package restore and mutation journal outside the golden home."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.qa_host_starting_state import validate_host_starting_state

PACKAGE_JOURNAL_SUFFIX = ".qa-packages.json"

# Executed by the host's existing credential-bound argv runner. The journal
# records the base inventory before mutation, so a killed command remains
# recoverable by the next mission without interpreting its command text.
_PACKAGE_SCRIPT = r"""
import json, os, pathlib, subprocess, sys
mode, journal_name, config_json = sys.argv[1:]
journal = pathlib.Path(journal_name)
assert journal.is_absolute() and not journal.is_symlink()
config = json.loads(config_json)
def inventory():
    result = subprocess.run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'],
                            capture_output=True, text=True, check=True)
    return {name: version for name, version, status in
            (line.split('\t') for line in result.stdout.splitlines()) if status == 'installed'}
def write(value):
    temporary = journal.with_suffix(journal.suffix + '.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, journal)
def apt(operation, packages):
    if packages:
        result = subprocess.run(['sudo', '-n', 'env', 'DEBIAN_FRONTEND=noninteractive',
                                 'apt-get', '-y', operation, *(['--allow-downgrades'] if operation == 'install' else []), '--', *packages],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('os_package_fixture_failed: verify passwordless package-fixture authority and apt repository access')
def delta(base, current):
    return {'installed': {name: version for name, version in current.items() if name not in base},
            'removed': {name: version for name, version in base.items() if name not in current},
            'changed': {name: version for name, version in base.items()
                        if name in current and current[name] != version}}
current = inventory()
previous = json.loads(journal.read_text()) if journal.exists() else None
if mode == 'restore':
    restored = delta(previous['base_packages'], current) if previous else delta(current, current)
    if previous:
        apt('purge', sorted(restored['installed']))
        apt('install', [name+'='+version for name, version in
                       {**restored['removed'], **restored['changed']}.items()])
        if inventory() != previous['base_packages']:
            raise RuntimeError('os_package_restore_unproved: reconcile package versions before retrying QA')
    base = inventory()
    write({'base_packages': base, 'declared': config, 'changes': delta(base, base)})
    required = config.get('os_packages', {})
    apt('purge', [name for name in required.get('absent', []) if name in base])
    apt('install', [name for name in required.get('present', []) if name not in base])
    current = inventory()
    present = all(name in current for name in required.get('present', []))
    absent = all(name not in current for name in required.get('absent', []))
    changes = delta(base, current)
    write({'base_packages': base, 'declared': config, 'changes': changes})
    print(json.dumps({'ok': present and absent, 'declared': config,
                      'restored_previous_changes': restored, 'changes': changes,
                      'journal_path': str(journal)}))
    if not present or not absent:
        sys.exit(1)
else:
    if previous is None:
        raise RuntimeError('os_package_journal_missing: run mission preparation before host commands')
    changes = delta(previous['base_packages'], current)
    previous['changes'] = changes
    write(previous)
    print(json.dumps({'ok': True, 'changes': changes, 'journal_path': str(journal)}))
"""


def _run(control: Any, mode: str, declared: dict | None) -> dict:
    if getattr(control, "os", None) not in {"linux", "windows"}:
        if declared:
            raise ValueError(
                "os_package_fixture_unsupported: apt fixtures require a Linux or WSL Test Machine"
            )
        return {
            "ok": True,
            "state": "not_applicable",
            "reason": "no apt package fixture on this OS",
        }
    golden = getattr(control, "golden_baseline_path", None)
    if not golden:
        raise ValueError(
            "os_package_journal_unavailable: declare a golden path outside the host home"
        )
    result = control.run_command(
        [
            "/usr/bin/python3",
            "-c",
            _PACKAGE_SCRIPT,
            mode,
            golden + PACKAGE_JOURNAL_SUFFIX,
            json.dumps(declared or {}),
        ],
        timeout=900,
    )
    try:
        evidence = json.loads(result.stdout)
    except (ValueError, TypeError):
        evidence = {}
    if result.returncode or evidence.get("ok") is not True:
        raise RuntimeError(
            "os_package_fixture_failed: restore could not prove the declared package state; "
            "check apt access, passwordless sudo and the journal beside the golden before retrying QA"
        )
    return evidence


def restore_host_packages(control: Any, declared: dict | None) -> dict:
    """Undo the preceding mission's complete package delta, then apply this fixture."""
    config = validate_host_starting_state(declared) if declared is not None else None
    return _run(control, "restore", config)


def record_host_packages(control: Any) -> dict:
    """Record direct and transitive package changes, including failed commands."""
    return _run(control, "record", None)
