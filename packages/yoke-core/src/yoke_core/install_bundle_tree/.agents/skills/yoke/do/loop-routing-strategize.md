# `/yoke do` Loop Routing — `strategize` handler

Extracted from [`loop-routing.md`](loop-routing.md) so that file stays under
the 350-line cap after the substrate failure taxonomy table was added in
Step B. The pointer in `loop-routing.md` Step B's per-action handler list
points back here.

## `strategize`

Print the strategy summary from `context`:
```
STRATEGIZE: {reason}
SML coherent: {sml_coherent}
Drift review: {drift_review_classification} — {drift_review_summary}
```

Then read `.agents/skills/yoke/strategize/SKILL.md` (resolve relative to
the workspace root) and follow its instructions inline. Keep the
decision-engine `context` visible as the rationale for why strategize was
chosen; the strategize flow still runs its full guided checkpoint sequence.

After the strategize flow completes, **stop the loop** -- this action is
NOT chainable.
