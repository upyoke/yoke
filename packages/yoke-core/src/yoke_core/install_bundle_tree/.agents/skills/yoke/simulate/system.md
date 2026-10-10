# Simulate: System audit

`--system` audits Yoke's own agents, skills, Python owners, rules, hooks and
docs. It requires a Yoke source checkout: verify the checkout contains
Yoke source repo only: `runtime/agents/`, `packages/yoke-core/src/yoke_core/` and
`docs/source-dev/system-simulation.md` before reading that guide.

In an installed project, stop with “--system requires a Yoke source checkout”;
use the epic simulation flow for that project's task graph.

In the verified source checkout, read `docs/source-dev/system-simulation.md`
and follow its report-only audit. This source-only guide is deliberately absent
from installed project documentation. System audits have no auto-fix loop.
