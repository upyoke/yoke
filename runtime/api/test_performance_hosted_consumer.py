"""Run the actual Platform path consumer against both route rosters.

The fixture is the committed consumer source, with its source identity next
to it. Platform materializes JS and this JSON together at build time; an
engine-only rollout cannot add links to its still-serving asset bundle.
"""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "packages/yoke-core/src/yoke_core/ui"
FIXTURES = Path(__file__).parent / "fixtures"


def test_current_host_consumer_accepts_new_roster_and_old_roster_remains_harmless():
    source = (FIXTURES / "hosted_dashboard_path_consumer.ts").read_text()
    metadata = json.loads(
        (FIXTURES / "hosted_dashboard_consumer_metadata.json").read_text()
    )
    assert hashlib.sha256(source.encode()).hexdigest() == metadata["consumer_sha256"]
    old = json.loads((FIXTURES / "hosted_dashboard_routes.json").read_text())
    candidate = json.loads((UI / "contracts/dashboard-routes.json").read_text())
    assert candidate["schemaVersion"] == old["schemaVersion"]
    assert candidate["hostedBasePathTemplate"] == old["hostedBasePathTemplate"]
    assert set(old["views"]).issubset(candidate["views"])
    script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('./node_modules/typescript');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const code = ts.transpileModule(input.source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, esModuleInterop: true,
} }).outputText;
function load(routes) {
  const exports = {};
  vm.runInNewContext(code, { exports, require: name => {
    assert.equal(name, '../../.generated/universe-contract/dashboard-routes.json'); return routes;
  }, URLSearchParams });
  return exports;
}
const previous = load(input.old), next = load(input.candidate);
assert.equal(previous.isHostedDashboardPath(['performance']), false);
assert.equal(next.isHostedDashboardPath(['performance']), true);
for (const view of input.old.views) {
  assert.equal(previous.isHostedDashboardPath([view]), true);
  assert.equal(next.isHostedDashboardPath([view]), true);
}
assert.equal(previous.isHostedDashboardPath(['unknown-destination']), false);
assert.equal(next.isHostedDashboardPath(['unknown-destination']), false);
assert.equal(previous.hostedDashboardBasePath('example'), next.hostedDashboardBasePath('example'));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=UI,
        input=json.dumps({"source": source, "old": old, "candidate": candidate}),
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
