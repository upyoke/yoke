# Usher — plan

Dry run only; write nothing and claim nothing:

```text
yoke items get PREFIX-N deployment_flow project --json
yoke deployment-runs resolve-target PROJECT FLOW
```

An empty target is merge-only; an unresolved one is never guessed. Print
order, route and approval stages, then "Dry run complete".
