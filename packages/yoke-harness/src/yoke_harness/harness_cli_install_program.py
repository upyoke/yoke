"""Host-side probe and verified installer, run as the test user without Yoke."""

HOST_PROGRAM = r"""
import errno, filecmp, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
pattern = re.compile(sys.argv[1])
# A full or failing disk (on WSL, a full Windows volume under ext4.vhdx makes
# Linux remount the root read-only) refuses every write, including scratch cleanup.
DISK_ERRNOS = {errno.EROFS, errno.ENOSPC, errno.EIO, errno.EDQUOT}
search = os.pathsep.join([str(Path.home() / '.local/bin'), os.environ.get('PATH', '')])

def probe(executable):
    record = dict(version=None, exit_code=None, stderr='', executable=executable)
    if not executable:
        record['stderr'] = 'executable not found in ~/.local/bin or PATH'
        return record
    try:
        result = subprocess.run([str(executable), '--version'], capture_output=True,
                                text=True, errors='replace', timeout=60)
        record.update(exit_code=result.returncode, stderr=result.stderr.strip()[:400])
        matched = pattern.search(result.stdout) if result.returncode == 0 else None
        record['version'] = matched.group(0).rstrip('-+._') if matched else None
        if not matched and not record['stderr']:
            record['stderr'] = 'unreadable version output: ' + result.stdout.strip()[:300]
    except (OSError, subprocess.TimeoutExpired) as error:
        record['stderr'] = str(error)[:400]
    return record

def resolve(names):
    return next((p for n in names if (p := shutil.which(n, path=search))), None)

def install(harness, names, script, wanted):
    receipt = dict(install_exit_code=None, install_stderr='')
    try:
        with tempfile.TemporaryDirectory(prefix='yoke-harness-') as temporary:
            install_into(receipt, Path(temporary) / 'executable', harness, names, script, wanted)
    except OSError as error:
        if error.errno not in DISK_ERRNOS:
            raise
        receipt['host_disk_error'] = dict(
            errno=errno.errorcode.get(error.errno, str(error.errno)),
            message=error.strerror, filename=str(error.filename))
    return receipt

def install_into(receipt, saved, harness, names, script, wanted):
    previous = resolve(names)
    before = probe(previous)
    original = Path(previous).resolve() if previous else None
    if before['version']:
        shutil.copy2(original, saved)
    try:
        result = subprocess.run(['/bin/sh', '-c', script, 'sh', wanted],
                                capture_output=True, text=True, errors='replace', timeout=540)
        receipt.update(install_exit_code=result.returncode,
                       install_stderr=result.stderr.strip()[:400])
    except (OSError, subprocess.TimeoutExpired) as error:
        receipt.update(install_stderr=str(error)[:400])
    observed = probe(resolve(names))
    receipt['probe'] = observed
    if observed['version']:
        return
    receipt['failed_probe'] = observed
    candidates = []
    # Cursor retains complete releases; its launcher needs the adjacent node.
    if harness == 'cursor':
        versions = Path.home() / '.local/share/cursor-agent/versions'
        candidates = sorted(versions.glob('*/cursor-agent'), reverse=True)
    if before['version']:
        original.parent.mkdir(parents=True, exist_ok=True)
        if (original.is_symlink() or not original.is_file()
                or not filecmp.cmp(saved, original, shallow=False)):
            if original.is_symlink():
                original.unlink()
            shutil.copy2(saved, original)
        candidates.append(original)
    for candidate in dict.fromkeys(candidates):
        if not probe(str(candidate))['version']:
            continue
        if harness == 'cursor':
            try:
                # The vendor's static channel prevents a real request from
                # relinking the incompatible release after --version passed.
                pinned = subprocess.run([str(candidate), 'set-channel', 'static'],
                    capture_output=True, text=True, errors='replace', timeout=60)
                if pinned.returncode:
                    raise RuntimeError(f'exit {pinned.returncode}: {pinned.stderr[:400]}')
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                receipt['install_stderr'] += (
                    '; Cursor set-channel static failed: ' + str(error)[:400])
                return
        local_bin = Path.home() / '.local/bin'
        local_bin.mkdir(parents=True, exist_ok=True)
        for name in names:
            link = local_bin / name
            if link == candidate:
                continue
            if link.is_symlink() or link.is_file():
                link.unlink()
            link.symlink_to(candidate)
        restored = probe(resolve(names))
        if restored['version']:
            receipt.update(probe=restored, held_back=True)
            break
    return

if sys.argv[2] == 'probe':
    records = {h: probe(resolve(names)) for h, names in json.loads(sys.argv[3])}
    output = {h: record['version'] or record for h, record in records.items()}
else:
    output = install(*json.loads(sys.argv[3]))
print(json.dumps(output))
"""
