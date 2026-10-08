"""Serve the real Performance component with a captured authorized production read.

This review surface never queries or seeds a test database. Supply the JSON
receipt from events.performance.aggregate; optional detail receipts retain only
rows in the inspected bucket. It publishes the same source-identity contract as
the workbench. The prototype directory is a separately checked-out reference.
"""
from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from yoke_core.ui.served_source_identity import served_build_identity
from yoke_core.ui.workbench_shell import served_build_response

PAGE = """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/theme.css">
<link rel="stylesheet" href="/static/universe_performance.css">
<style>body{margin:0;padding:12px;font-family:system-ui;background:#f5f7fa;color:#202633}
main{background:white;border:1px solid #dfe3eb;border-radius:10px;max-width:1300px;margin:auto}
.panel-header h2{margin:0;flex:1;font-size:20px}footer{font-size:11px;margin:12px;color:#667}</style>
<main></main><footer id="source"></footer>
<script type="module">
import {renderPerformanceView} from '/static/universe_views_performance.js';
const aggregate=await (await fetch('/aggregate')).json();
const detail=await (await fetch('/detail')).json();
const sha=await (await fetch('/served-build')).text();
document.querySelector('#source').textContent=`Production snapshot · ${aggregate.result.observation_count} retained observations · ${aggregate.result.queried_at} · served source ${sha}`;
const client={call:async request=>{
 if(request.function==='events.performance.aggregate')return {envelope:aggregate};
 const p=request.payload;
 const rows=detail.result.rows.filter(r=>Date.parse(r.observed_at)>=Date.parse(p.since)&&Date.parse(r.observed_at)<Date.parse(p.until)&&(!p.family||r.family===p.family));
 return {envelope:{success:true,result:{...detail.result,rows,total:rows.length,next_offset:null,sampling:'captured longest 50 observations; bucket-filtered review snapshot'}}};
}};
renderPerformanceView({document,client,signal:new AbortController().signal},document.querySelector('main'),'all');
</script>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--detail", type=Path, required=True)
    parser.add_argument("--prototype-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18843)
    args = parser.parse_args()
    receipts = {"/aggregate": args.aggregate.read_bytes(), "/detail": args.detail.read_bytes()}
    for value in receipts.values():
        if not json.loads(value).get("success"):
            parser.error("performance_review_read_failed: supply successful authorized receipts")
    import yoke_core
    static = Path(yoke_core.__file__).parent / "ui" / "static"

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/served-build":
                response = served_build_response(served_build_identity())
                content = response.body
            elif path in receipts:
                content = receipts[path]
            elif path == "/":
                content = PAGE.encode()
            elif path == "/comparison":
                content = b"""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>
<style>body{margin:0;font:14px system-ui}section{display:flex;gap:8px}article{width:50%;min-width:0}iframe{width:100%;height:1000px;border:0}h2{font-size:16px;margin:10px}</style>
<section><article><h2>Approved prototype</h2><iframe src='/yoke-web-prototype.html#cost-performance'></iframe></article><article><h2>Candidate · production snapshot</h2><iframe src='/'></iframe></article></section>"""
            else:
                return super().do_GET()
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if path in ("/", "/comparison") else "text/plain" if path == "/served-build" else "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def translate_path(self, path):
            path = urlsplit(path).path
            root = static if path.startswith("/static/") else args.prototype_root
            relative = path.removeprefix("/static/") if path.startswith("/static/") else path.lstrip("/")
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()):
                return str(root / "missing")
            return str(target)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Production snapshot component review: http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
