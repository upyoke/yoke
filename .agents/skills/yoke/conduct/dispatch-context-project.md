# Conduct — project context

Run for every project-owned item, including Yoke. Projectless skips only this
block; development still requires verified project attribution before lanes.

```text
yoke items get PREFIX-N project
yoke machine detail --json
python3 -m yoke_core.domain.context_routing get-always {PROJECT}
python3 -m yoke_core.domain.context_routing list-topics {PROJECT}
python3 -m yoke_core.domain.context_routing get-topic {PROJECT} {TOPIC}
```

The retained source-dev routing owner reads the Project Structure family, not
copied config. Include always paths plus configured topics matched to title:
frontend/dashboard/UI→frontend; backend/api/server→backend; test/testing→testing;
deploy/deployment→deployment. Read matched docs from the machine mapping's
registered checkout. Missing doc warns with exact path and skips that doc;
missing mapping names project register recovery, never projects.path or a
guessed repository. Emit each successfully read filename/content once.

```text
yoke qa plan list --project {PROJECT} --json
yoke qa requirement list --item PREFIX-N --json
yoke ephemeral-env get {PROJECT} {BRANCH} --json
```

Carry plan names/transition attachments and materialized requirement id,
case_key, method, instructions and expected outcome. Read exact snapshots;
never reparse embedded commands or invent test invocations. Runnable rows use:

```text
yoke qa case run --requirement-id {requirement_id}
```

Read the actual registered worktree branch's environment. Missing/unhealthy
sets URL=none; no inferred PREFIX-N branch/table query. Context contains project,
checkout, exact lane, selected control-plane authority, QA roster and preview
URL. Work stays inside this project's selected lane. Then independently run
[dispatch-context-ephemeral.md](dispatch-context-ephemeral.md) when capability
exists; refresh URL/candidate identity after it completes. The shared Tester
template owns prompt variants and consumes these facts.
