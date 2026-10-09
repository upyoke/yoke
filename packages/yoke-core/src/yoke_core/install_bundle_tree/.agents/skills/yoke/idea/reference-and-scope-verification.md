# Idea — Verify References and Scope

Before proposing paths/symbols in inference, drafting or edits, inspect the
actual registered target checkout. Use test -d for directories and the Glob
tool or rg --files for files; absent paths require live re-derivation or a
clarification, never intuition. Discover the project's verified one-shot migration package root and active skill layout, not another project's tree.

Gate owners:
```bash
rg -n 'def _run_.*_gate|def check_.*_gate|GATE_[A-Z_]+' <source-roots>
rg -n '^def <funcname>' <source-roots> <docs-and-agent-instruction-roots>
```

Verify definitions before naming them. workflow_runtime.py interprets immutable
item stage/gates; task_lifecycle.py owns independent task vocabulary. Discover
source/doc roots from actual project rules/tree. Quote literal patterns for zsh.
Item bodies are virtual DB reads through `yoke items get PREFIX-N body`,
never filesystem search. Readiness repeats these checks.

Every required path remains in intent and each enabled budget/claim surface.
Independent edits get attested coordination_only; ordered edits need directional
activation evidence; coordinate/wait for holders where needed. Operator override
is last resort under the deep lane rules, never a scope-removal workaround.
