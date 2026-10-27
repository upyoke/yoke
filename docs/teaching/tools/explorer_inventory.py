"""Build provenance for the Sources guide."""

import re


def source_path(value):
    return re.sub(r":\d+(?:-\d+)?$", "", value).split("#")[0].removeprefix("../../../")


def source_snapshot(nodes, pages):
    """Fingerprint inspected inputs; never present an old research claim as reverified."""
    from datetime import datetime, timezone
    import hashlib
    import json
    from pathlib import Path
    import subprocess
    import sys
    from model import all_records, model_files

    repo = Path(__file__).resolve().parents[3]
    paths = set(model_files())
    paths.update(Path(__file__).parent.glob("*"))
    paths.update(repo / path for path in pages.docs)
    for node in nodes:
        if node.get('document'):
            paths.add(repo / source_path(node['document']))
    for _, _, record in all_records(pages.m):
        paths.update(repo / source_path(path) for path in record.get('sources', []))
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(repo) and '.venv' not in path.parts:
                paths.add(path)
    digest = hashlib.sha256()
    count = 0
    for path in sorted(paths):
        if path.is_file() and path.is_relative_to(repo):
            digest.update(str(path.relative_to(repo)).encode())
            digest.update(path.read_bytes())
            count += 1
    digest.update(json.dumps({k: sorted(v) for k, v in pages.live.items()}, sort_keys=True).encode())
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True))
    return dict(built_at=datetime.now(timezone.utc).isoformat(), commit=commit,
                dirty=dirty, input_files=count, input_digest=digest.hexdigest())
