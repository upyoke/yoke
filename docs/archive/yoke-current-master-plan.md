# Yoke — Master Plan
*Generated from design session, March 2026*

---

## How To Use This Document

This is the authoritative reference for Yoke's next evolution. It covers:
1. Updates to VISION.md
2. The complete new architecture and data model
3. Every ticket that needs to be created, updated, or closed
4. A deferral log tracking what's explicitly out of scope and why

Tickets are grouped by epic. Each ticket has enough detail to be entered directly into Yoke via `/yoke idea` and shepherded immediately.

---

# PART 1 — VISION.md UPDATES

The following sections of VISION.md require rewriting. The rest remains valid.

---

## Mission (unchanged)

No change needed. The mission statement accurately describes what Yoke is becoming.

---

## Strategy — Delivery Model (minor update)

The three-phase strategy (Agency → Managed → Self-serve) is correct. One clarification needed:

**Phase 2 — Managed mode** currently references "a web dashboard." Replace with: clients interact through an operator-facing interface built on top of Yoke's API layer. The interface is not part of v1 — the API is the foundation that makes it possible. Phase 2 begins when the API exists and is stable enough to build on.

---

## Product Vision — 1 Month (full rewrite)

**Current text is obsolete** — it references "the Yoke Dashboard" as the first external project, which no longer exists as a concept.

**Replace with:**

> Yoke manages two projects: itself and Buzz (a real deployed web application). The Yoke API server is a live site within the Yoke project — a FastAPI service running locally that exposes Yoke's state over HTTP. At least one Buzz item has gone through the full pipeline: shepherded, composed into a sprint, conducted by the engineer and tester agents working in a Buzz worktree, merged to Buzz's main branch, and ushered through its deployment flow to the production droplet. The Usher skill exists and handles post-merge delivery.
>
> Key capabilities at 1 month:
> - Project domain model in DB — items target a project, conduct resolves repo_path, worktrees created in target repo
> - Context bundle assembly — conduct injects project AGENTS.md, relevant docs, test commands into engineer prompt
> - Deployment flows — named, per-project flow library; Shepherd selects flow during item definition
> - Usher skill — reads deployment flow, executes stages, halts cleanly on capability gaps or approval gates
> - `needs-capability` and `awaiting-approval` as first-class item states visible on the board
> - Yoke API site configured — FastAPI running locally, `api-deploy` deployment flow defined
> - Buzz project configured — repo_path, context files, test commands, SSH capability, deployment flows
> - One Buzz item delivered end-to-end through the full pipeline including production deployment
> - `deploy_stage` column on items; board shows project, site, and deploy_stage as columns

---

## Product Vision — 6 Months (targeted updates)

Replace CDK-specific references with generalized infrastructure language:

- "CDK template library for common app architectures" → "infrastructure template library covering common deployment patterns (Docker + VPS, serverless, static site); new patterns added as Yoke encounters them across projects"
- "Client-facing dashboard with project-scoped logins" → keep, but note this is built on top of the Yoke API (vUtopia)
- Remove specific CDK/AWS assumptions throughout

Add:
- Ephemeral branch environments for pre-merge E2E validation on deployed-app projects
- Adaptive E2E testing (Playwright + screenshot + LLM fallback) as a first-class capability type
- Capability dependency resolution — `aws-route53` inherits from `aws-admin`, etc.

---

## Product Vision — 1 Year (minor updates)

- "Infrastructure engineer agent with CDK expertise" → "Infrastructure engineer agent with blast-radius-aware deployment gates; provider-agnostic, CDK is one capability among many"
- "Session scheduler managing concurrent agent sessions" → keep as-is, still accurate

---

## Technical Strategy — Architecture (update one paragraph)

The "control plane pattern" description is accurate. Add one paragraph:

> Yoke itself is a project in its own DB. It has a repo (the scripts, agents, and skills), and it has sites — the API server being the first. Items targeting Yoke's internal scripts have no site and complete at merge. Items targeting the API server have a deployment flow that ends with a local process restart and health check. This self-referential model is not a special case — Yoke uses its own pipeline to build itself, and the same pipeline handles any other project.

---

## Technical Strategy — Data Architecture (full rewrite of planned extensions)

Replace the numbered list of planned schema extensions with:

> See Part 2 of the Master Plan for the complete schema design. The build order is: (1) projects + items.project, (2) deployment_flows, (3) sites + environments, (4) project_capabilities, (5) deploy_stage on items + deployment_events rewrite, (6) ephemeral_environments, (7) agent_events (YOK-407).

---

## Technical Strategy — API Layer (full rewrite)

Replace the current section (which describes a dashboard-backend API with three options for shell script integration) with:

> The Yoke API is a FastAPI service that runs as a site within the Yoke project. It reads and writes the same `yoke.db` that the shell scripts use. For now, shell scripts continue to use sqlite3 directly — the API and the scripts are parallel consumers of the same DB, not layered on top of each other. The API is the foundation for external consumers: the operator dashboard (vUtopia), future client-facing interfaces, and eventually project-specific Claude Code sessions that need to communicate with Yoke's state without filesystem access.
>
> The API is versioned from day one. v1 exposes read endpoints for all board state and write endpoints for idea submission and gate approval. vUtopia adds the operator dashboard. Authentication starts as localhost-only (no auth); future versions add API key per caller, then session-based auth for multi-user scenarios.
>
> Shell script migration to API calls is explicitly deferred. Scripts call sqlite3 directly today and will continue to do so until there is a concrete reason to change — performance, remote access, or multi-writer contention. The deferral log tracks this decision.

---

## Technical Strategy — Infrastructure (full rewrite)

Replace the CDK-focused section with:

> Yoke provisions infrastructure through a capability template library. A capability template defines what a deployment mechanism requires (credentials, config shape, commands) and how to execute it. Templates are provider-agnostic — rsync+Docker, AWS Lambda, DigitalOcean Apps, Fly.io, and others are all capability types. New templates are invented on demand: when Yoke encounters a deployment pattern it hasn't seen before, it defines the template, saves it to the library, and uses it immediately.
>
> Infrastructure changes of any kind — new environments, DNS changes, SSL certificates, server provisioning — require human approval gates regardless of risk level. The blast radius of infrastructure mistakes is unbounded. This is non-negotiable and applies to all projects including Yoke itself.
>
> CDK is a future capability type for AWS-native projects. It is not the assumed default.

---

## Technical Strategy — What To Avoid (update one item)

Remove: *"The repo is called Yoke. We may rename it eventually..."* — the name is settled permanently. Yoke is Yoke.

Replace with: *"Don't rename Yoke. The name is correct. The snake eating its tail is the right metaphor for a system that improves itself."*

---

---

# PART 2 — COMPLETE DATA MODEL

---

## Items Table — New Columns

```sql
ALTER TABLE items ADD COLUMN project TEXT NOT NULL DEFAULT 'yoke' REFERENCES projects(id);
ALTER TABLE items ADD COLUMN deployment_flow TEXT REFERENCES deployment_flows(id);
ALTER TABLE items ADD COLUMN deploy_stage TEXT DEFAULT NULL;
-- deploy_stage values: null (not yet merged), or any stage name from the flow,
-- or: needs-capability, awaiting-approval, complete
-- items.status = 'done' only when deploy_stage = 'complete' (or flow is null/internal)
```

**Updated status vocabulary:**

| Status | Owned by | Meaning |
|--------|----------|---------|
| `idea` | Human / Shepherd | Filed, not yet defined |
| `defined` | Shepherd | PM + Architect have specified it |
| `planned` | Shepherd | Architecture decomposed (epics) |
| `ready` | Shepherd | All gates passed, ready to conduct |
| `active` | Conduct | Engineer dispatched |
| `passed` | Conduct | Engineer + Tester + Simulator passed |
| `merged` | Conduct | Merged to target branch |
| `needs-capability` | Usher | Blocked on missing/misconfigured capability |
| `awaiting-approval` | Usher | Blocked on human approval gate |
| `done` | Usher | deploy_stage = complete (or no-deploy flow) |
| `cancelled` | Human | Explicitly cancelled |

**Note on `deploy_stage`:** This column tracks position within the deployment flow after merge. It is null until the item is merged. The board displays it as a column alongside status. Items with `status=merged` and a non-null `deploy_stage` are "in the Usher's hands."

---

## New Table: projects

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,                    -- e.g. 'yoke', 'buzz'
  name TEXT NOT NULL,                     -- display name
  repo_path TEXT NOT NULL,               -- absolute local path to repo
  default_branch TEXT DEFAULT 'main',
  context_always TEXT DEFAULT '[]',       -- JSON array of file paths always injected
  context_by_topic TEXT DEFAULT '{}',    -- JSON object: topic -> [file paths]
  test_command_quick TEXT,               -- fast test suite command
  test_command_full TEXT,                -- full test suite command
  test_command_e2e TEXT,                 -- e2e test suite command
  deploy_triggers TEXT DEFAULT '{}',     -- JSON: {branch: flow_id} merge trigger map
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Seed data
INSERT INTO projects (id, name, repo_path, context_always, test_command_quick, test_command_full)
VALUES (
  'yoke',
  'Yoke',
  '/Users/dev/yoke',  -- update to actual path
  '["CLAUDE.md", "yoke/README.md"]',
  'sh .claude/skills/yoke/scripts/tests/run-all.sh --fast',
  'sh .claude/skills/yoke/scripts/tests/run-all.sh'
);

INSERT INTO projects (id, name, repo_path, context_always, context_by_topic,
                      test_command_quick, test_command_full, test_command_e2e,
                      deploy_triggers)
VALUES (
  'buzz',
  'Buzz',
  '/Users/dev/buzz',
  '["AGENTS.md", "docs/OVERVIEW.md"]',
  '{
    "backend": ["docs/API.md", "docs/PIPELINE.md"],
    "frontend": ["docs/DASHBOARD.md"],
    "testing": ["docs/TESTING.md"],
    "deployment": ["docs/VPS-SETUP.md"],
    "logging": ["docs/LOGGING.md"]
  }',
  'cd app && python3 -m pytest tests/ -k "not live" && cd web && npm run test',
  'cd app && python3 -m pytest tests/ -k "not live" && cd web && npm run test && npm run build',
  'cd app/web && npm run test:e2e',
  '{"main": "buzz-prod-release", "hotfix": "buzz-prod-hotfix"}'
);
```

---

## New Table: deployment_flows

```sql
CREATE TABLE deployment_flows (
  id TEXT PRIMARY KEY,                    -- e.g. 'buzz-prod-release'
  project TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL,                     -- human display name
  description TEXT,
  stages TEXT NOT NULL,                   -- JSON array of stage objects
  on_failure TEXT DEFAULT 'halt',         -- 'halt' | 'requeue' | 'skip'
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project, name)
);
```

**Stage object schema:**
```json
{
  "name": "staging-deploy",
  "executor": "deploy-command",
  "env": "staging",
  "on_failure": "halt",
  "auto": true
}
```

**Executor types (v1 closed set):**

| Executor | What it does | Required config |
|----------|-------------|-----------------|
| `auto` | No-op, advance immediately | none |
| `deploy-command` | Run project deploy script | `env` |
| `health-check` | HTTP GET, expect 2xx | `url` or `env` (looked up from environments table) |
| `test-suite` | Run named test suite | `suite` (maps to project test_command_*) |
| `adaptive-e2e` | Playwright + screenshot + LLM fallback | `suite`, `env` |
| `ephemeral-deploy` | Spin up branch environment | `env_template` |
| `ephemeral-teardown` | Tear down branch environment | `env_template` |
| `human-approval` | Halt, wait for `/yoke approve` | optional `notify` |
| `script` | Run arbitrary shell command | `command`, `working_dir` |

**Seed deployment flows:**

```sql
-- Yoke: internal script change (no deployment)
INSERT INTO deployment_flows (id, project, name, description, stages) VALUES (
  'yoke-internal', 'yoke', 'Internal', 'Script/doc changes, no deployment needed',
  '[{"name":"merged","executor":"auto"},{"name":"complete","executor":"auto"}]'
);

-- Yoke: API site deployment
INSERT INTO deployment_flows (id, project, name, description, stages) VALUES (
  'yoke-api-deploy', 'yoke', 'API Deploy', 'Deploy to local FastAPI server',
  '[
    {"name":"merged","executor":"auto"},
    {"name":"api-restart","executor":"script","command":"./scripts/restart-api.sh"},
    {"name":"health-check","executor":"health-check","url":"http://localhost:8765/health"},
    {"name":"complete","executor":"auto"}
  ]'
);

-- Buzz: sprint release (full flow)
INSERT INTO deployment_flows (id, project, name, description, stages, on_failure) VALUES (
  'buzz-prod-release', 'buzz', 'Sprint Release', 'Full staging → regression → approval → prod',
  '[
    {"name":"merged","executor":"auto"},
    {"name":"staging-deploy","executor":"deploy-command","env":"staging"},
    {"name":"staging-verify","executor":"health-check","env":"staging"},
    {"name":"regression","executor":"test-suite","suite":"full"},
    {"name":"review","executor":"human-approval"},
    {"name":"prod-deploy","executor":"deploy-command","env":"production"},
    {"name":"smoke","executor":"health-check","env":"production"},
    {"name":"complete","executor":"auto"}
  ]',
  'halt'
);

-- Buzz: hotfix (skip staging, direct to prod with smoke)
INSERT INTO deployment_flows (id, project, name, description, stages, on_failure) VALUES (
  'buzz-prod-hotfix', 'buzz', 'Hotfix', 'Direct to production with smoke test',
  '[
    {"name":"merged","executor":"auto"},
    {"name":"prod-deploy","executor":"deploy-command","env":"production"},
    {"name":"smoke","executor":"health-check","env":"production"},
    {"name":"complete","executor":"auto"}
  ]',
  'halt'
);

-- Buzz: internal doc/config change
INSERT INTO deployment_flows (id, project, name, description, stages) VALUES (
  'buzz-internal', 'buzz', 'Internal', 'Doc or config change, no deployment',
  '[{"name":"merged","executor":"auto"},{"name":"complete","executor":"auto"}]'
);
```

---

## New Table: sites

```sql
CREATE TABLE sites (
  id TEXT PRIMARY KEY,                    -- e.g. 'yoke-api', 'buzz-web'
  project TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL,                     -- display name
  description TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Seed
INSERT INTO sites VALUES ('yoke-api', 'yoke', 'Yoke API', 'FastAPI control plane API', datetime('now'));
INSERT INTO sites VALUES ('buzz-web', 'buzz', 'Buzz Web', 'Buzz dashboard + API on DO droplet', datetime('now'));
```

---

## New Table: environments

```sql
CREATE TABLE environments (
  id TEXT PRIMARY KEY,                    -- e.g. 'yoke-api-local', 'buzz-web-prod'
  site TEXT NOT NULL REFERENCES sites(id),
  name TEXT NOT NULL,                     -- 'local', 'staging', 'production'
  url TEXT,
  deploy_method TEXT,                    -- 'script', 'docker-compose', 'rsync+docker', etc.
  deploy_command TEXT,                   -- command to run for deployment
  health_check_url TEXT,
  config_notes TEXT,
  last_deployed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(site, name)
);

-- Seed
INSERT INTO environments VALUES (
  'yoke-api-local', 'yoke-api', 'local',
  'http://localhost:8765', 'script',
  'cd /Users/dev/yoke && ./scripts/restart-api.sh',
  'http://localhost:8765/health',
  'FastAPI running locally via uvicorn', NULL, datetime('now')
);

INSERT INTO environments VALUES (
  'buzz-web-production', 'buzz-web', 'production',
  'http://100.115.178.33:3000', 'rsync+docker',
  'cd /Users/dev/buzz && ./deploy.sh',
  'http://100.115.178.33:8000/api/health',
  'DigitalOcean droplet, Docker Compose', NULL, datetime('now')
);
```

---

## New Table: project_capabilities

```sql
CREATE TABLE project_capabilities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL REFERENCES projects(id),
  type TEXT NOT NULL,                     -- capability type id from capability_templates
  config TEXT NOT NULL,                   -- JSON, shape defined by template
  verified_at TEXT,                       -- last successful verification
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project, type)
);
```

---

## New Table: capability_templates

```sql
CREATE TABLE capability_templates (
  id TEXT PRIMARY KEY,                    -- e.g. 'ssh', 'aws-admin', 'docker', 'ephemeral-env'
  name TEXT NOT NULL,
  description TEXT,
  required_config TEXT NOT NULL,         -- JSON array of {key, description, secret: bool}
  requires TEXT DEFAULT '[]',            -- JSON array of capability type ids (dependencies)
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Seed: core capability types
INSERT INTO capability_templates VALUES (
  'ssh', 'SSH Access',
  'SSH access to a remote server',
  '[
    {"key":"user","description":"SSH username","secret":false},
    {"key":"host","description":"Server hostname or IP","secret":false},
    {"key":"key_path","description":"Path to SSH private key","secret":false}
  ]',
  '[]', datetime('now')
);

INSERT INTO capability_templates VALUES (
  'docker', 'Docker',
  'Docker daemon accessible for container operations',
  '[{"key":"host","description":"Docker host (default: local)","secret":false}]',
  '[]', datetime('now')
);

INSERT INTO capability_templates VALUES (
  'ephemeral-env', 'Ephemeral Environment',
  'Ability to spin up and tear down per-branch environments',
  '[
    {"key":"base_port","description":"Base port for this project ephemeral envs","secret":false},
    {"key":"compose_file","description":"docker-compose file for ephemeral env","secret":false},
    {"key":"env_file","description":"Path to .env file for ephemeral env secrets","secret":false},
    {"key":"startup_timeout_s","description":"Seconds to wait for health check after start","secret":false}
  ]',
  '["docker"]', datetime('now')
);

INSERT INTO capability_templates VALUES (
  'aws-admin', 'AWS Admin',
  'AWS credentials with broad admin access. Parent for all AWS capabilities.',
  '[
    {"key":"access_key_id","description":"AWS Access Key ID","secret":true},
    {"key":"secret_access_key","description":"AWS Secret Access Key","secret":true},
    {"key":"region","description":"Default AWS region","secret":false}
  ]',
  '[]', datetime('now')
);

INSERT INTO capability_templates VALUES (
  'aws-route53', 'AWS Route53',
  'DNS management via Route53. Requires aws-admin.',
  '[{"key":"hosted_zone_id","description":"Route53 Hosted Zone ID","secret":false}]',
  '["aws-admin"]', datetime('now')
);

-- Seed: Buzz capabilities
INSERT INTO project_capabilities (project, type, config) VALUES (
  'buzz', 'ssh',
  '{"user":"openclaw","host":"45.55.157.144","key_path":"~/.ssh/id_rsa"}'
);

INSERT INTO project_capabilities (project, type, config) VALUES (
  'buzz', 'docker',
  '{"host":"local"}'
);

INSERT INTO project_capabilities (project, type, config) VALUES (
  'buzz', 'ephemeral-env',
  '{"base_port":9000,"compose_file":"docker-compose.yml","env_file":"~/buzz-secrets/.env.test","startup_timeout_s":30}'
);
```

---

## New Table: ephemeral_environments

```sql
CREATE TABLE ephemeral_environments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL REFERENCES projects(id),
  branch TEXT NOT NULL,
  item TEXT,                              -- YOK-N that created it
  port_api INTEGER,
  port_web INTEGER,
  status TEXT NOT NULL DEFAULT 'starting', -- starting, running, stopped, failed
  started_at TEXT,
  stopped_at TEXT,
  health_check_url TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project, branch)
);
```

---

## Deployment Events — Wipe and Replace

**Drop existing table** (zero rows, schema was a stub).

```sql
DROP TABLE deployment_events;

CREATE TABLE deployment_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item TEXT NOT NULL,                     -- YOK-N
  project TEXT NOT NULL REFERENCES projects(id),
  flow TEXT REFERENCES deployment_flows(id),
  stage TEXT NOT NULL,                    -- stage name from flow
  executor TEXT NOT NULL,                 -- executor type used
  result TEXT NOT NULL,                   -- pass, fail, skip, halted
  detail TEXT,                            -- human-readable detail / error output
  capability_needed TEXT,                 -- if result=halted: what capability is missing
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);
```

---

## BOARD.md — Minimal Changes

The item display table gains three new columns. No new art system. No per-project boards yet.

**Current columns:** ID | Status | Priority | Type | Progress | Title

**New columns:** ID | Status | Project | Site | Deploy Stage | Priority | Type | Progress | Title

- `Project` — the project id (yoke, buzz). Short, fits in a column.
- `Site` — the site id if the item's deployment flow targets a site, else `—`
- `Deploy Stage` — current `deploy_stage` value if post-merge, else `—`

Items at `needs-capability` or `awaiting-approval` get a distinct emoji marker: 🔑 and ⏳ respectively.

---

---

# PART 3 — NEW SKILL: USHER

---

## Usher — Character Definition

The Usher takes merged work and guides it through the deployment flow to production. It is a first-class pipeline skill with its own SKILL.md — like Shepherd, Compose, and Conduct, it runs in the main session when invoked via `/yoke usher`.

**Invocation:** `/yoke usher YOK-N`

**Ownership:** post-merge lifecycle. The Usher owns `merged → done`. It does not touch anything pre-merge.

**Principle:** Stateless invocation, stateful DB. The Usher reads `deploy_stage` from the DB on startup and picks up from where it left off. Re-invoking `/yoke usher YOK-N` on an item at `staging-deploy` resumes from staging-deploy. Re-invoking on a complete item is a no-op.

**Orchestration principle:** The Usher runs in the main session, calls executor scripts via Bash, reads their exit codes, updates DB state via `yoke-db.sh`, and exits cleanly on halt conditions. It does not write application code, does not modify test files, does not make judgment calls about whether a failure is acceptable.

---

## Usher — State Machine

```
Entry point: item.status = 'merged', deploy_stage = null (or any non-complete stage for resume)

For each stage in flow.stages (starting from current deploy_stage or beginning):
  1. Write deploy_stage = stage.name to items table
  2. Write deployment_events row: started
  3. Dispatch executor for stage type
  4. Read exit code:
     - 0 (pass): write deployment_events completed=pass, continue to next stage
     - 1 (fail): write deployment_events completed=fail
       - if stage.on_failure = 'halt': set item.status = 'merged' + deploy_stage = '{stage}-failed', exit
       - if stage.on_failure = 'requeue': set item.status = 'active', clear deploy_stage, exit (conduct will re-dispatch)
       - if stage.on_failure = 'skip': log warning, continue to next stage
     - 2 (needs-capability): set item.status = 'needs-capability', record capability_needed in deployment_events, exit
     - 3 (awaiting-approval): set item.status = 'awaiting-approval', exit

On final stage (complete):
  Set item.status = 'done', deploy_stage = 'complete'
```

---

## Usher — Executor Scripts

Each executor type maps to a script. All scripts live in `.claude/skills/yoke/scripts/executors/`.

| Script | Executor type | Exit codes |
|--------|--------------|------------|
| `exec-auto.sh` | auto | 0 always |
| `exec-deploy-command.sh` | deploy-command | 0=pass, 1=fail, 2=needs-capability |
| `exec-health-check.sh` | health-check | 0=pass, 1=fail |
| `exec-test-suite.sh` | test-suite | 0=pass, 1=fail |
| `exec-adaptive-e2e.sh` | adaptive-e2e | 0=pass, 1=fail |
| `exec-ephemeral-deploy.sh` | ephemeral-deploy | 0=pass, 1=fail, 2=needs-capability |
| `exec-ephemeral-teardown.sh` | ephemeral-teardown | 0=pass, 1=fail |
| `exec-human-approval.sh` | human-approval | 3=awaiting-approval always (until approved) |
| `exec-script.sh` | script | 0=pass, 1=fail, 2=needs-capability |

---

## Capability Self-Invention Protocol

When any executor encounters a missing or unconfigured capability:

1. Executor exits with code 2 and writes to stdout:
   ```
   CAPABILITY_NEEDED: {type}
   REASON: {why this capability is required}
   TEMPLATE: {existing template id, or 'NEW' if novel}
   NEW_TEMPLATE_SPEC: {JSON template definition if novel}
   ```

2. Usher reads this output, writes to `deployment_events.capability_needed`

3. If `TEMPLATE = 'NEW'`: Usher saves the new template to `capability_templates` table

4. Usher sets `item.status = 'needs-capability'`

5. Usher prints to operator:
   ```
   ⛔ CAPABILITY NEEDED: {type}
   Item YOK-N is halted at stage {stage}.
   
   Required: {template description}
   Config needed:
     - {key}: {description}
     - ...
   
   Once configured, run: /yoke usher YOK-N to resume.
   ```

6. **Usher exits. Does not attempt to proceed. Does not guess.**

The operator configures the capability (adds a row to `project_capabilities`) and re-runs `/yoke usher YOK-N`. The Usher resumes from the halted stage.

---

## `/yoke approve YOK-N` Command

When an item is at `awaiting-approval`:

```
/yoke approve YOK-N [--note "optional approval note"]
```

This:
1. Writes an approval record to `deployment_events` (result=approved, detail=note)
2. Sets `item.status = 'merged'` (back to Usher-owned state)
3. Prints: `Approved. Run /yoke usher YOK-N to continue deployment.`

The operator then re-runs `/yoke usher YOK-N` to resume from the next stage after the approval gate.

---

## Conduct Changes for Usher Handoff

**merge-worktree.sh** — currently sets `item.status = 'done'`. Change to: set `item.status = 'merged'`. Do not set deploy_stage yet.

**conduct SKILL.md** — after merge step, add:

```
Post-merge: Check item's deployment_flow.
- If null or 'internal'-type flow: immediately invoke Usher for this item.
  The Usher will complete in seconds (merged → complete → done).
- If non-trivial flow: invoke Usher. It will run automated stages and halt
  if it hits a human gate or capability gap. Report halt condition to operator.
- In all cases: the conduct does NOT set item.status = 'done' directly.
  The Usher owns done.
```

---

---

# PART 4 — SHEPHERD CHANGES

---

## New: Deployment Flow Selection in idea_to_defined

The Shepherd's `idea_to_defined` transition gains a new required output: **deployment flow selection**.

After the PM writes the item spec, before the Boss verdict, the Shepherd must determine:

1. What project does this item target? (read from item or infer from context)
2. Does this item result in a deployed change (code that runs somewhere) or an internal change (scripts, docs, config)?
3. If deployed: which site does it target?
4. Which configured deployment flow is appropriate for this change?

The Shepherd writes its selection to the item body as a new section:

```markdown
## Definition of Done

- **Project:** buzz
- **Site:** buzz-web (or: none — internal change)
- **Deployment Flow:** buzz-prod-release
- **Flow rationale:** This change touches the dashboard frontend and requires
  full regression testing before production deployment.
```

If no appropriate flow exists in the project's library, the Shepherd flags this:

```markdown
## Definition of Done

- **Project:** buzz
- **Site:** buzz-web
- **Deployment Flow:** ⚠️ NEEDS NEW FLOW
- **Suggested flow:** [description of what stages are needed]
- **Action required:** Create deployment flow before this item can be conducted.
```

The Boss verdict for `idea_to_defined` must verify that a deployment flow is selected or flagged. Missing deployment flow = NOT_READY.

---

## Updated Lifecycle Check in Shepherd SKILL

The "if item is already at ready or later, skip" check must be updated to include all new statuses:

```
Skip if status in: ready, active, passed, merged, needs-capability, 
                   awaiting-approval, done, cancelled
```

---

---

# PART 5 — CONDUCT CHANGES

---

## Context Bundle Assembly for External Projects

When conducting an item with `project != 'yoke'`, the conduct must assemble a project context bundle before dispatching the engineer.

**New step 5f-project (runs before 5f-issue or 5f-epic):**

```bash
_project=$(sh "$SCRIPT_DIR/yoke-db.sh" items get "$_id" project)
_project_path=$(sh "$SCRIPT_DIR/yoke-db.sh" query \
  "SELECT repo_path FROM projects WHERE id='$_project'")

if [ "$_project" != "yoke" ]; then
  # Read context_always files
  _context_always=$(sh "$SCRIPT_DIR/yoke-db.sh" query \
    "SELECT context_always FROM projects WHERE id='$_project'")
  
  # Determine topic from item title/body (heuristic or stored tag)
  # Read relevant context_by_topic files
  
  # Assemble context bundle string
  _project_context="
=== PROJECT CONTEXT: {project.name} ===
You are working on a project called {project.name}.
Repo location: {project.repo_path}
Your worktree: {worktree_path}
Yoke DB: {MAIN_ROOT}/yoke/yoke.db

Project conventions and architecture:
--- {context_always[0]} ---
{file contents}
--- {context_always[1]} ---
{file contents}

Do NOT modify Yoke's own scripts or config.
All Yoke DB operations still use: {MAIN_ROOT}/.claude/skills/yoke/scripts/yoke-db.sh
All code changes go to your worktree: {worktree_path}
=== END PROJECT CONTEXT ===
"
fi
```

This bundle is prepended to the engineer's prompt.

---

## Worktree Creation for External Projects

**create-worktree.sh** currently assumes `REPO_ROOT` is Yoke's repo. It must accept an optional `--project` flag:

```bash
create-worktree.sh <id-number> [--project <project-id>]
```

When `--project buzz` is passed:
1. Look up `repo_path` from projects table
2. Run `git worktree add` from inside the Buzz repo, not Yoke's repo
3. Worktree lands at `{buzz_repo_path}/.worktrees/YOK-{N}`
4. Return the worktree path

The conduct passes `--project` when the item's project is not 'yoke'.

---

---

# PART 6 — TICKET INVENTORY

Everything below is a ticket. Grouped by epic. Each includes type, priority, dependencies, and full spec detail sufficient for Shepherd to process.

---

## EPIC A: Project Domain Model
**Priority:** Critical — blocks all external project work
**Type:** Epic
**Depends on:** Nothing

### A-1: projects table + items.project column
**Type:** Issue | **Priority:** Critical

Create the `projects` table per the schema in Part 2. Add `project` column to `items` table (DEFAULT 'yoke'). Create `project-db.sh` domain wrapper with subcommands: `init`, `create`, `get`, `list`, `update`. Register in `yoke-db.sh` router. Seed `yoke` project record with correct local repo_path. Add Doctor HC: item with nonexistent project id.

### A-2: Buzz project seed data
**Type:** Issue | **Priority:** Critical | **Depends on:** A-1

Insert Buzz project record per Part 2 seed data. Insert `sites` and `environments` records for buzz-web. Insert `project_capabilities` records for buzz (ssh, docker, ephemeral-env). Insert `capability_templates` for all v1 types. Verify all FK relationships. Doctor HC: project with repo_path that is not a git repo.

### A-3: Conduct worktree creation for external projects
**Type:** Issue | **Priority:** Critical | **Depends on:** A-1

Update `create-worktree.sh` to accept `--project` flag. Look up `repo_path` from projects table. Run `git worktree add` in target repo. Update conduct SKILL.md step 5e to pass `--project` when `item.project != 'yoke'`. Update `merge-worktree.sh` to resolve the correct repo root based on item's project. Test: create worktree for a Buzz item, verify it lands in Buzz's `.worktrees/`.

### A-4: Context bundle assembly
**Type:** Issue | **Priority:** Critical | **Depends on:** A-1, A-2

Implement step 5f-project in `dispatch-context.md` per Part 5 spec. Read `context_always` files from project repo, embed contents in engineer prompt. Read relevant `context_by_topic` files based on item title keyword matching (simple heuristic: if title contains "frontend"/"dashboard"/"UI" → include frontend topic; "API"/"endpoint"/"backend" → backend topic; etc.). Prepend project context block to engineer prompt. Update engineer agent frontmatter with note that working directory and project context come from prompt, not from Claude Code's root.

### A-5: BOARD.md project/site/deploy_stage columns
**Type:** Issue | **Priority:** High | **Depends on:** A-1

Update `rebuild-board.sh` to add Project, Site, and Deploy Stage columns to the Pipeline and Backlog item tables. Site column: look up item's deployment_flow → flow's stages → find deploy-command stage → get site. Or null if internal flow. Deploy Stage: item.deploy_stage value, or `—` if null. Items at `needs-capability` get 🔑 prefix. Items at `awaiting-approval` get ⏳ prefix. Doctor HC: item with deploy_stage set but status not in (merged, needs-capability, awaiting-approval, done).

---

## EPIC B: Deployment Flows
**Priority:** Critical
**Type:** Epic
**Depends on:** Epic A

### B-1: deployment_flows table + flow-db.sh
**Type:** Issue | **Priority:** Critical | **Depends on:** A-1

Create `deployment_flows` table per Part 2 schema. Create `flow-db.sh` domain wrapper: `init`, `create`, `get`, `list`, `stages` (parse and return stage array). Register in `yoke-db.sh` router. Seed all flows from Part 2 (yoke-internal, yoke-api-deploy, buzz-prod-release, buzz-prod-hotfix, buzz-internal). Doctor HC: project with no deployment flows configured.

### B-2: Wipe deployment_events, create new schema
**Type:** Issue | **Priority:** Critical | **Depends on:** B-1

Drop existing `deployment_events` table (zero rows — safe). Create new schema per Part 2. Update `composer-db.sh` init to use new schema. Update any references in `doctor.sh` schema validation. Update test files that reference old schema. Create `deployment-yoke-db.sh events` domain wrapper (or add to flow-db.sh): `record-start`, `record-complete`, `record-halt`, `list-for-item`.

### B-3: items.deployment_flow + items.deploy_stage columns
**Type:** Issue | **Priority:** Critical | **Depends on:** B-1

Add `deployment_flow` (FK to deployment_flows.id) and `deploy_stage` (TEXT) columns to items table. Update `item-db.sh` to handle these fields. Update `backlog-registry.sh` item creation to accept deployment_flow parameter. Update `rebuild-board.sh` to read deploy_stage (handled in A-5 but depends on this column existing). Doctor HC: item with status=done but deploy_stage != 'complete' and deployment_flow is not null.

### B-4: Shepherd deployment flow selection
**Type:** Issue | **Priority:** Critical | **Depends on:** B-1, B-3

Update `shepherd/idea-to-defined.md` (or equivalent) to include deployment flow selection step per Part 4 spec. PM worker prompt gains new required output section: "Definition of Done" with project, site, flow selection, rationale. Boss verdict for idea_to_defined gains new check: deployment flow must be selected or explicitly flagged as needing creation. Update `shepherd/boss-verdict.md` with new verdict criterion. Update shepherd SKILL.md lifecycle check to include new statuses.

---

## EPIC C: Usher Skill
**Priority:** Critical
**Type:** Epic
**Depends on:** Epic A, Epic B

### C-1: Executor scripts (executors/ directory)
**Type:** Issue | **Priority:** Critical | **Depends on:** B-1, B-2

Create `.claude/skills/yoke/scripts/executors/` directory. Implement all executor scripts per Part 3 table. Each script: reads config from environment or arguments, performs its action, exits with documented exit codes, writes structured output for capability-needed cases. Test each executor in isolation. `exec-auto.sh` and `exec-health-check.sh` first (simplest). `exec-deploy-command.sh` and `exec-test-suite.sh` second. `exec-human-approval.sh` third. Deferred to later sprint: `exec-adaptive-e2e.sh`, `exec-ephemeral-deploy.sh`, `exec-ephemeral-teardown.sh`.

### C-2: deploy-pipeline.sh orchestrator
**Type:** Issue | **Priority:** Critical | **Depends on:** C-1, B-2, B-3

Create `deploy-pipeline.sh`. Accepts: item id, optional `--from-stage` for resume. Reads item's deployment_flow. Iterates stages. For each stage: writes deploy_stage to items, calls appropriate executor script, reads exit code, records deployment_events, handles pass/fail/halt per state machine in Part 3. On capability-needed: prints structured output to operator, sets status=needs-capability, exits. On awaiting-approval: sets status=awaiting-approval, exits. On complete: sets status=done, deploy_stage=complete. Idempotent: if stage already in deployment_events as pass, skip it.

### C-3: Usher SKILL.md and router entry
**Type:** Issue | **Priority:** Critical | **Depends on:** C-2

Create `.claude/skills/yoke/usher/SKILL.md` with full invocation spec: parse YOK-N, read item, check status is merged or resumable, invoke `deploy-pipeline.sh`, parse output, report result. Add `/yoke usher` entry to the root SKILL.md router. No agent definition file — the Usher runs in the main session, calls executor scripts via Bash, reads their exit codes, and updates DB state via `yoke-db.sh`.

### C-4: /yoke approve command
**Type:** Issue | **Priority:** Critical | **Depends on:** C-2

Create `/yoke approve` SKILL.md. Accepts `YOK-N` and optional `--note`. Validates item is at `awaiting-approval`. Writes approval record to `deployment_events`. Resets `item.status = 'merged'`. Prints resume instructions. Does NOT auto-resume — operator runs `/yoke usher YOK-N` to continue. Doctor HC: item stuck at `awaiting-approval` for >72h without activity.

### C-5: Conduct handoff to Usher
**Type:** Issue | **Priority:** Critical | **Depends on:** C-3

Update `merge-worktree.sh` to set `item.status = 'merged'` instead of `done`. Update conduct `conduct/batch-flow.md` and `conduct/single-item.md` post-merge steps: after merge, invoke `/yoke usher YOK-N` for the merged item. Usher runs inline (not as background job). For items with no-op flows (internal), Usher completes immediately and item goes to done as before. For items with non-trivial flows, Usher runs until halt or completion. Conduct reports Usher outcome in its final summary.

---

## EPIC D: Yoke API Site
**Priority:** High
**Type:** Epic
**Depends on:** Epic A, Epic B, Epic C

### D-1: FastAPI server scaffold
**Type:** Issue | **Priority:** High | **Depends on:** A-1

Create `yoke/api/` directory inside the Yoke repo. FastAPI app with: `/health` endpoint, `/items` list endpoint (filterable by project, status), `/items/{id}` get endpoint, `/sprints` list endpoint, `/board` endpoint (returns current board state as JSON). SQLite connection reading `yoke/yoke.db` (read-only for v1). `requirements.txt`. `start-api.sh` script: starts uvicorn on port 8765. `restart-api.sh` script: kills existing process, starts fresh. README with setup instructions. This is `project=yoke, site=yoke-api`.

### D-2: Yoke API deployment flow validation
**Type:** Issue | **Priority:** High | **Depends on:** D-1, C-5

File a Buzz-style item targeting the Yoke API: "Verify yoke-api-deploy flow works end-to-end." Shepherd it, conduct it, Usher it. This validates: the `yoke-api-deploy` deployment flow executes correctly, `exec-deploy-command.sh` restarts the API, `exec-health-check.sh` confirms it's healthy, item reaches done. This is the first item to go through the full Usher pipeline.

### D-3: API write endpoints
**Type:** Issue | **Priority:** Medium | **Depends on:** D-1

Add write endpoints to the Yoke API: `POST /items` (create idea — calls `backlog-registry.sh` via subprocess for now), `POST /items/{id}/approve` (approve gate — calls `/yoke approve` logic). `POST /items/{id}/capability` (configure a capability for the item's project). These are the minimum needed for a future operator UI.

---

## EPIC E: Buzz First Item — Validation
**Priority:** High
**Type:** Epic
**Depends on:** All of A, B, C

### E-1: Buzz v1 validation item
**Type:** Issue | **Priority:** High | **Depends on:** A-2, C-5

File a real Buzz item via `/yoke idea`. Something small but real — a backend bug fix, a small feature, or a doc improvement. Shepherd it (including deployment flow selection — expect buzz-prod-release or buzz-internal). Compose it into a sprint. Conduct it (engineer works in Buzz worktree, tester runs Buzz tests). Merge it. Usher it through the deployment flow. Document every failure. Every failure becomes a Yoke ticket. Success criteria: item reaches `status=done` with `deploy_stage=complete` without manual intervention beyond the human-approval gate.

---

## EPIC F: Ephemeral Environments
**Priority:** Medium (post-validation)
**Type:** Epic
**Depends on:** Epic A, Epic C, Buzz project configured

### F-1: ephemeral_environments table + env-db.sh
**Type:** Issue | **Priority:** Medium | **Depends on:** A-2

Create `ephemeral_environments` table per Part 2 schema. Create `env-db.sh` wrapper: `create`, `get`, `update-status`, `list-active`, `cleanup-stale`. Doctor HC: ephemeral environment in 'running' status for >2h (likely zombie).

### F-2: exec-ephemeral-deploy.sh
**Type:** Issue | **Priority:** Medium | **Depends on:** F-1, C-1

Implement `exec-ephemeral-deploy.sh`. Reads project's `ephemeral-env` capability config. Computes port from base_port + (item_id % 100). Writes `ephemeral_environments` row. Runs docker-compose with dynamic port env vars and env-file. Polls health check URL up to startup_timeout_s. Exits 0 on healthy, 1 on timeout/failure, 2 if ephemeral-env capability not configured. On failure: runs teardown before exiting.

### F-3: exec-ephemeral-teardown.sh
**Type:** Issue | **Priority:** Medium | **Depends on:** F-1

Implement `exec-ephemeral-teardown.sh`. Reads ephemeral_environments record for branch. Runs docker-compose down for that instance. Updates status to 'stopped'. Cleans up port allocation. Always exits 0 (teardown failures are logged but not fatal).

### F-4: Conduct ephemeral env lifecycle
**Type:** Issue | **Priority:** Medium | **Depends on:** F-2, F-3

Update conduct dispatch for Buzz items: before Engineer dispatch, check if project has `ephemeral-env` capability. If yes, spin up ephemeral environment for the branch (exec-ephemeral-deploy.sh). Inject ephemeral env URL into tester prompt so E2E tests run against it. After Tester returns (pass or fail), always run teardown. Zombie cleanup: on conduct session start, run env-db.sh cleanup-stale and tear down any ephemeral envs older than 2h.

---

## EPIC G: Tester Agent Enhancements for Deployed Apps
**Priority:** Medium (post-validation)
**Type:** Epic
**Depends on:** Epic F

### G-1: Tester project-aware test execution
**Type:** Issue | **Priority:** Medium | **Depends on:** A-4

Update tester agent prompt and SKILL.md to: read project's `test_command_quick` and `test_command_full` from DB rather than assuming Yoke's test commands. Run tests from the correct working directory (worktree root for the target project). Report results in the standard format. This is the minimum needed for the tester to work on Buzz without modification.

### G-2: Adaptive E2E executor
**Type:** Issue | **Priority:** Medium | **Depends on:** F-2

Implement `exec-adaptive-e2e.sh`. Runs `test_command_e2e` against the ephemeral environment URL. If Playwright tests fail due to selector errors (detected by output pattern matching), escalates to screenshot + LLM analysis mode: takes screenshots of the failing page, sends to a vision-capable model with the test code, gets suggested selector fixes, applies fixes, retries. Maximum 3 adaptive cycles before reporting failure. Records all attempts in deployment_events detail field.

---

## EXISTING TICKETS — Actions Required

### Close (superseded)
- **YOK-51** — Close. Replaced by Epic A entirely. The 16 tasks it contained were workarounds for the missing project model.
- **YOK-126** — Close. Replaced by deployment flows + Usher. All 8 tasks obsolete.
- **YOK-227** — Close. Smoke is a first-class deployment flow stage.

### Rewrite body (keep, update spec)
- **CI integration idea** — If revived later, rewrite as: "implement `ci-check` executor type for deployment flows, with GitHub Actions status polling as the first implementation." Remove old impl details.
- **YOK-228** — Rewrite as: "render deployment history view from new deployment_events schema." Update schema references.
- **Manual stage-resume idea** — If revived later, rewrite as: "manual `/yoke usher YOK-N --from-stage {stage}` for re-running a specific deployment stage on an already-merged item without filing a new ticket."

### Keep unchanged — ship in next sprint
- **YOK-487** — epic_task_files UNIQUE constraint
- **YOK-492** — find_project_root() worktree resolution
- **YOK-493** — ingest-body GitHub sync
- **YOK-495** — merge-worktree.sh cleanup trap
- **YOK-498** — agents.md missing 4 agents
- **YOK-499** — HC-37 auto-generate known keys
- **YOK-500** — find_project_root() deduplication
- **YOK-501** — classify-dirty-files deduplication
- **YOK-533** — YOK-454 spec contradiction fix
- **YOK-551** — Doctor HC epics without simulation
- **YOK-554** — Conduct session performance

### Keep unchanged — deferred
- **Doc merge preservation idea** — grows in importance, not urgent
- **Mandatory motivation-context idea** — dovetails with Shepherd flow selection
- **Epic splitting idea** — deferred
- **Scholar-style research-lane idea** — deferred
- **Multi-audience release summaries idea** — deferred
- **YOK-333** — Remove dead dual-write bridge (small cleanup, any sprint)
- **YOK-407** — Structured logging (keep, unblock after Epic A lands)
- **YOK-431** — Event registry (keep, depends on YOK-407)

---

## PAD.md — Actions Required

### Remove from PAD (now ticketed above or closed)
- Project Domain Model ticket → Epic A
- Site/Environment Model ticket → Epic A + B
- Test Gates and Approval Gates ticket → Usher + deployment flows
- Deploy Command and Orchestration ticket → Epic C
- First External Client Project → Epic E
- Testing harness system for web apps → Epic F + G
- Observability Hook Infrastructure → superseded by YOK-407 (already noted in PAD)

### Keep in PAD (unticketed, valid)
- Ouroboros product vision framework → narrow ticket: "add Strategic Alignment section to PRD template"
- StrongDM competitive landscape research → low priority research item
- Wisdom preservation mechanism → extend patterns.md categories
- ouroboros.dev website → deferred
- Rename Yoke → Ouroboros → **DEAD. Yoke is Yoke.**

---

---

# PART 7 — DEFERRAL LOG

This log tracks every explicit deferral decision. Versions are: v1 (current build), vUtopia (long-term target).

| Feature | Deferred to | Reason |
|---------|-------------|--------|
| Operator dashboard UI | vUtopia | API must stabilize first. No client need yet. |
| API authentication | vUtopia | Localhost-only. No multi-user scenario yet. |
| Shell scripts → API migration | vUtopia | Scripts work fine on sqlite3. No concrete reason to change yet. |
| AWS Route53 / DNS management | Next sprint after Buzz validated | Need AWS capability configured. Buzz validation first. |
| HTTPS / SSL for any site | Next sprint | Depends on DNS capability. |
| CDK infrastructure templates | 6-month horizon | No AWS-native projects yet. |
| Multi-model routing (Haiku/Sonnet/Opus) | 6-month horizon | Don't optimize cost before proving business model. |
| Session scheduler (concurrent projects) | 1-year horizon | Single Mac, single session for now. |
| Active pattern propagation | After scenario framework | Needs scenario validation to measure improvement. |
| Scenario validation framework | After Epic E | Needs real multi-project operation to design meaningful scenarios. |
| Push-based ouroboros loop | After YOK-407 | Needs structured events to trigger on. |
| Per-project BOARD-{project}.md | After multi-project validated | Minimal board changes (columns) first. |
| Board art for multi-project | After per-project boards | No art changes until board structure is proven. |
| exec-adaptive-e2e.sh | Epic G (post-validation) | Needs ephemeral envs first. Complex. |
| exec-ephemeral-deploy.sh | Epic F (post-validation) | Validate basic pipeline first. |
| Test registration in Yoke DB | Post-Epic G | Tester project-awareness first. Intelligence layer second. |
| Cross-project pattern transfer | 6-month horizon | Need 3+ projects operating to have meaningful cross-project signal. |
| Anomaly-to-ticket pipeline | After YOK-407 ships | Needs agent_events table. |
| Client self-serve onboarding | Self-serve phase | Phase 3. |
| ouroboros.dev website | Long-term | Not blocking anything. |
| Yoke rename to Ouroboros | Never | Yoke is Yoke. |

---

---

# PART 8 — EXECUTION SEQUENCE

## Sprint 1: Foundation (Epics A + B core)
Ship the data model and the Shepherd changes. No Usher yet — validate the schema is right.

**Items:**
- Close YOK-51, YOK-126, YOK-227 (update status, add close notes)
- Rewrite the CI integration idea, YOK-228, and the manual stage-resume idea
- Ship YOK-487, 492, 493, 495, 498, 499, 500, 501, 533 (small ready items — clear the pipeline)
- Epic A: A-1, A-2, A-3, A-4, A-5
- Epic B: B-1, B-2, B-3, B-4

**Success criteria:**
- `projects` table exists, buzz and yoke seeded
- `items.project` column exists, defaults to 'yoke'
- `deployment_flows` table exists, all seed flows present
- Shepherd selects deployment flows during definition
- Board shows project/site/deploy_stage columns
- Conduct creates worktrees in Buzz repo for buzz-targeted items
- Context bundle assembled and injected into engineer prompt

## Sprint 2: Usher + First Buzz Item (Epics C + D + E)
Ship the Usher skill and validate the full pipeline end-to-end.

**Items:**
- Epic C: C-1 through C-5
- Epic D: D-1, D-2
- Epic E: E-1 (the validation item — this is the sprint's success criterion)

**Success criteria:**
- `/yoke usher YOK-N` works
- One Buzz item goes from idea to `status=done, deploy_stage=complete`
- Yoke API running locally with health endpoint
- Every failure during E-1 generates a new Yoke ticket

## Sprint 3: Ephemeral Environments + Tester Enhancement (Epics F + G)
**Contingent on Sprint 2 success.** Don't start until E-1 completes cleanly.

**Items:**
- YOK-407 (Structured Logging — unblock now that foundation is stable)
- Epic D: D-3 (API write endpoints)
- Epic F: F-1 through F-4
- Epic G: G-1, G-2

---

---

# PART 9 — OPEN QUESTIONS LOG

Questions that came up during design and don't have a final answer yet. Each needs a decision before the relevant ticket is implemented.

| # | Question | Context | Owner |
|---|----------|---------|-------|
| 1 | Conduct same-session vs queued Usher invocation | Currently spec'd as same-session. May need to be async if Usher takes too long and blows conduct turn budget. | Revisit after Sprint 2 E-1. |
| 2 | Branch environment DNS vs port routing | Spec uses port offsets (9000, 9010, etc.). May need Tailscale-based routing if ports conflict with other local services. | Revisit in Epic F. |
| 3 | Ephemeral env secrets on remote server | `.env.test` file works on Mac. When Yoke moves to Linux server, needs a different secrets strategy (Vault, SSM, encrypted file). | Deferred to server migration. |
| 4 | GitHub Actions integration | Should Yoke optionally fire a GH Actions workflow on merge instead of running Usher directly? Powerful for teams, overkill for solo. | Revisit when first client project onboards. |
| 5 | Capability config encryption | Capability configs store SSH keys, API credentials as JSON. Currently plaintext in SQLite. Needs encryption at rest before any multi-user or remote scenario. | Deferred to vUtopia / remote server migration. |
| 6 | Deployment flow failure → requeue behavior | `on_failure: requeue` sends item back to `active`. But the original fix may require understanding the deployment failure context. Should the conduct get that context? | Spec during Epic C implementation. |
| 7 | `deploy_triggers` branch mapping | Currently spec'd as project-level config. Should individual items be able to override which branch triggers their flow? | Decide during B-4 implementation. |

---

---

# PART 10 — SYSTEM COVERAGE AUDIT

This part answers: does the master plan cover every aspect of the current system that is affected by the new architecture? Short answer: no, the original plan had gaps. This part closes them.

---

## 10.1 — Tables With No Project-Awareness Decision

Every table in yoke.db needs an explicit decision: does it need a `project` column, and if not, why not?

| Table | Needs project? | Decision |
|-------|---------------|---------|
| `items` | YES | Add `items.project` column — already specced in Part 2 |
| `ouroboros_entries` | YES — gap | See below |
| `release_entries` | YES — gap | See below |
| `wrapup_reports` | YES — gap | See below |
| `conduct_progress` | NO | Conduct progress is per-sprint-track, not per-project. Items already carry project. |
| `conduct_batch_summaries` | NO | Same — sprint/track scoped, items carry project |
| `shepherd_verdicts` | NO | Verdict is per-item. Item carries project. Query by item to get project context. |
| `caveat_dispositions` | NO | Per-item, same reasoning |
| `composer_sessions` | NO | Per-sprint. Sprint items carry project. |
| `composer_operations` | NO | Per-item within session |
| `final_boss_conditions` | NO | Per-session/item |
| `epic_tasks` | NO — but see below | Epic tasks inherit project from parent item. No separate column needed, but epic dispatch queries need to join through items to get project. |
| `epic_dispatch_chains` | NO | Inherits from epic item |
| `epic_task_files` | NO | Inherits from epic item |
| `epic_task_history` | NO | Inherits from epic item |
| `epic_progress_notes` | NO | Inherits from epic item |
| `epic_simulations` | NO | Inherits from epic item |
| `designs` | NO | Per-item |
| `reviews` | NO | Per-item |
| `item_dependencies` | NO | Dependent/blocking items carry project |
| `merge_locks` | NO | Merge lock is per-branch/session. Project inferable from item. |
| `sprints` | NO — but add project filter to queries | Sprints are global. Items within a sprint carry project. Multi-project sprints are allowed by design. |
| `tracks` | MAYBE — gap | See below |
| `sync_failures` | NO | Per-item |

---

### ouroboros_entries — needs project column

**The gap:** `ouroboros_entries` has `agent`, `context`, `category`, `body`. When Yoke is running work on Buzz, a tester reflection entry should be tagged with `project=buzz` not `project=yoke`. Right now there's no way to distinguish "this friction point is about Buzz's test suite" from "this friction point is about Yoke's merge pipeline."

**Decision:** Add `project TEXT NOT NULL DEFAULT 'yoke' REFERENCES projects(id)` to `ouroboros_entries`. All existing rows get `project='yoke'` via migration. All ouroboros write paths (`ouroboros-db.sh insert-entry`) gain a `--project` parameter. All agents writing ouroboros entries get project context injected in their prompt (already covered by context bundle assembly in Part 5, but ouroboros-db.sh calls need updating).

**New ticket:** O-1 — ouroboros_entries.project column + ouroboros-db.sh --project flag

---

### release_entries — needs project column

**The gap:** `release_entries` stores per-item release notes. When Buzz items are done, their release entries should be tagged `project=buzz`. `/yoke release-notes` should be filterable by project. PURIM.md and equivalent sprint release docs should either be per-project or clearly show which project each entry belongs to.

**Decision:** Add `project TEXT NOT NULL DEFAULT 'yoke' REFERENCES projects(id)` to `release_entries`. Backfill via migration (join through items). Update `release-notes-db.sh` and `done-transition.sh` to write project when recording release entries. Update release-notes SKILL.md to support `--project` filter.

**New ticket:** O-2 — release_entries.project column + filter support

---

### wrapup_reports — needs project awareness

**The gap:** `wrapup_reports` is a session-level document. A session that worked on Buzz items should note that in the wrapup — what projects were touched, how many items per project completed, etc. Right now wrapup is purely Yoke-centric.

**Decision:** Wrapup reports are session-scoped, not project-scoped, so no `project` column needed. But the wrapup SKILL.md should be updated to include a "Projects touched this session" summary section derived from querying items completed during the session by project. No schema change needed — the data is already in items.

**Impact:** Update wrapup SKILL.md only. Low effort.

---

### tracks — project awareness question

**The gap:** Tracks are currently per-sprint, and sprints are global (multi-project items can coexist in one sprint). The original plan said "tracks are project-homogeneous" — a track can only contain items from one project. But the tracks table has no `project` column to enforce this.

**Decision:** Add `project TEXT NOT NULL DEFAULT 'yoke' REFERENCES projects(id)` to `tracks`. This makes the homogeneity constraint enforceable by the DB and queryable by the board. Composer's track assignment phase must respect this: when assigning items to tracks, items with `project=buzz` go to buzz tracks, items with `project=yoke` go to yoke tracks. Mixed-project tracks are a validation error.

The board can then show track-level project labels and the conduct can resolve the correct repo for all items in a track without per-item lookups.

**New ticket:** O-3 — tracks.project column + compose enforcement + conduct track-level project resolution

---

## 10.2 — Skills and Agent Definitions Requiring Updates

The following SKILL.md files and agent definitions need explicit updates that are not yet covered in the plan. These are not just "will be affected by new tables" — these need specific new content.

---

### ouroboros-db.sh insert-entry

Currently: positional args, no project parameter, hard to use correctly (YOK-350 fixed validation but didn't add project). Needs `--project` flag. All callers need updating.

**Callers to update:** conduct SKILL.md (post-pipeline reflection), wrapup SKILL.md, curate SKILL.md, simulate SKILL.md, tester agent definition, engineer agent definition.

Covered by: **O-1**

---

### doctor.sh — new health checks needed for multi-project system

Current HCs don't know about projects, sites, environments, capabilities, or deployment flows. New HCs needed:

| HC | Check |
|----|-------|
| HC-new-1 | Item with `project` that doesn't exist in projects table |
| HC-new-2 | Project with `repo_path` that is not a git repo or doesn't exist |
| HC-new-3 | Item with `deployment_flow` set but flow doesn't exist in deployment_flows table |
| HC-new-4 | Item with `deploy_stage` set but `status` not in (merged, needs-capability, awaiting-approval, done) |
| HC-new-5 | Item with `status=done` but `deploy_stage != 'complete'` and `deployment_flow` is not null |
| HC-new-6 | Project with no deployment flows configured |
| HC-new-7 | Ephemeral environment in 'running' status for >2h (zombie) |
| HC-new-8 | Item at `needs-capability` or `awaiting-approval` for >72h with no deployment_events activity |
| HC-new-9 | Track with mixed projects (track.project != item.project for any item in that track) |
| HC-new-10 | Site with no environments configured |

Covered by: **O-4** — Add multi-project health checks to doctor.sh

---

### agents.md — currently documents all 8 agents (YOK-579 updated count from 11→8)

YOK-579 removed Conduct, Composer, and Shepherd agent wrappers (now SKILL.md-only). Agent count is 8. YOK-498 scope narrowed to verifying Boss and Final Boss documentation accuracy. Usher is a skill, not an agent — it gets a `commands.md` entry (O-6), not an `agents.md` entry.

**O-5 dropped.** Usher is a skill invoked via `/yoke usher` in the main session. No agents.md entry needed.

---

### commands.md — needs Usher and approve commands

`commands.md` currently documents all `/yoke` commands. New commands to add: `/yoke usher`, `/yoke approve`. Also update `/yoke conduct` description to note that it now hands off to usher post-merge.

**New ticket:** O-6 — Update commands.md for new commands (usher, approve, updates to conduct)

---

### db-reference.md — will be significantly stale

`db-reference.md` is the agent-facing DB schema reference (critical for preventing hallucinated SQL). After the new tables land it will be missing: projects, deployment_flows, sites, environments, project_capabilities, capability_templates, ephemeral_environments, new deployment_events schema, and new columns on items, ouroboros_entries, release_entries, tracks.

This is a mandatory update — stale db-reference.md directly causes agent errors (YOK-250 was filed exactly for this reason).

**New ticket:** O-7 — Rebuild db-reference.md to include all new tables and columns

---

### state-management.md — status lifecycle is now more complex

`state-management.md` documents the item status lifecycle. After the new model lands, it needs to cover: `merged`, `needs-capability`, `awaiting-approval`, `deploy_stage` as a parallel tracking field, and the full post-merge pipeline. The current doc ends at `done` without addressing how items get there in the new model.

**New ticket:** O-8 — Update state-management.md for new post-merge lifecycle

---

### worktree-lifecycle.md — external project worktrees are new

`worktree-lifecycle.md` documents how worktrees are created, used, and torn down. Currently assumes Yoke's own repo as the only target. Needs a new section: "External project worktrees" covering `--project` flag, target repo location, namespace in `.worktrees/` of target repo, and cleanup.

**New ticket:** O-9 — Update worktree-lifecycle.md for external project worktrees

---

### OVERVIEW.md — agent count and system description

`OVERVIEW.md` says "Eight agents" (YOK-579 reduced from eleven to eight by removing Shepherd, Composer, Conduct agent wrappers; Usher is a skill, not an agent). Also the system description doesn't mention multi-project operation, the API, or the Usher. Needs a full refresh.

**Impact:** Update after Usher lands. Can fold into O-6.

---

### session.md (Always Do First) — project context

`session.md` tells agents what to read on startup. Currently: recent commits + BOARD.md. After the multi-project model lands, agents operating on a non-Yoke project should also read that project's `context_always` files. The session startup should detect the active project from the current item or operator instruction and inject the right context.

This is subtle — session.md is injected for all Claude Code sessions including Yoke's own development sessions. It shouldn't unconditionally load Buzz docs. But a session kicked off by the conduct for a Buzz item should know to load them.

**Decision:** The project context injection happens at conduct dispatch time (already in Part 5 as the context bundle). Session.md doesn't need to change for this. But session.md should mention that multi-project context is injected by the conduct, not by session startup, so agents don't get confused.

**Impact:** One-line addition to session.md. Fold into O-8.

---

### CLAUDE.md — stale after new architecture

CLAUDE.md is the root instruction file. It currently describes a Yoke-only system. After the new model lands it needs: mention of multi-project support, the new status values (merged, needs-capability, awaiting-approval), and that items.project is the authoritative project reference.

**Impact:** Fold into O-7 or O-8. Small changes.

---

### release-notes SKILL.md

Needs `--project` filter support. Currently generates release notes for all items regardless of project. For Buzz, you want Buzz-specific release notes, not mixed with Yoke internal changes.

Covered by: **O-2**

---

### conduct SKILL.md (batch-flow.md and single-item.md)

Currently, after merge the conduct calls `done-transition.sh` and marks item done. This fundamentally changes in the new model:
- `merge-worktree.sh` sets `status=merged` not `done`
- Conduct then invokes Usher
- Conduct reports Usher result

`conduct/batch-flow.md` and `conduct/single-item.md` both need updating for the new post-merge handoff.

Covered by: **C-5** (already specced) — confirmed.

---

### done-transition.sh — major changes

`done-transition.sh` is the highest-traffic, most brittle script in the system (YOK-285, YOK-322, YOK-353 all targeting it). Its current job: handle the full post-merge ceremony (status update, release notes, board rebuild, GitHub sync, cleanup).

In the new model: `done-transition.sh` for Yoke-internal items still runs as before (no deployment flow). For items with a deployment flow, the Usher calls the final done transition after the pipeline completes. The ceremony steps themselves don't change — just who calls them and when.

**Decision:** `done-transition.sh` stays but gains an awareness check: if item has a deployment flow and `deploy_stage != 'complete'`, refuse to run (the Usher will call it when appropriate). This prevents the conduct from accidentally short-circuiting the deployment pipeline.

**New ticket:** O-10 — done-transition.sh deployment flow guard

---

### weave SKILL.md

`/yoke weave` is the batch merge orchestrator. It merges all passed items. After the new model, "merged" no longer means "done" — it means "handed to Usher." Weave needs to know this: after merging each item, invoke the Usher for that item. Items with no-op deployment flows will complete immediately. Items with real flows will run until first halt.

Weave currently runs items in order to avoid merge conflicts. This sequencing constraint still applies to the merge step. But the Usher runs for each item after its merge — Usher invocations could theoretically be parallelized if items target different projects and don't share environments. For now: sequential is fine.

**New ticket:** O-11 — Update weave SKILL.md to invoke Usher after each merge

---

### standup SKILL.md

`/yoke standup` generates a session standup summary. After the new model, standup should include: items currently in deployment pipeline (deploy_stage != null, != complete), any items halted at needs-capability or awaiting-approval. Currently it only shows items by pre-merge status.

**New ticket:** O-12 — Update standup SKILL.md to include deployment pipeline state

---

### status SKILL.md

`/yoke status YOK-N` shows item status. Needs to show `deploy_stage` and Usher-related fields when applicable.

**Impact:** Small — fold into O-12 or handle in the standup ticket.

---

### resync SKILL.md and backlog-resync.sh

`/yoke resync` does bidirectional GitHub sync. After the new model, GitHub issues for Buzz items need to sync to a GitHub repo that may be different from Yoke's GitHub repo. Currently `sync-to-github.sh` is hardcoded to Yoke's repo (read from `yoke/config`).

**The gap:** Items with `project=buzz` should sync to Buzz's GitHub repo, not Yoke's. This requires per-project GitHub config.

**New ticket:** O-13 — Per-project GitHub repo config for sync (project-level github_repo_url, github_repo_owner fields)

This is actually a new column on the `projects` table. Add to A-1 or create as O-13.

---

## 10.3 — Complete Affected Ticket and PAD Registry

Every existing ticket and PAD item, with its disposition under the new architecture. This is the authoritative list.

---

### ACTIVE TICKETS — Non-Done

| ID | Title (abbreviated) | Current status | Disposition |
|----|---------------------|----------------|-------------|
| YOK-51 | Project-awareness for any repo | planned | **CLOSE** — superseded by Epic A entirely. This was the placeholder. Real work is now A-1 through A-5. |
| YOK-126 | CI/CD environment progression | planned | **CLOSE** — superseded by deployment flows + Usher. The staged environment progression (local→dev→staging→prod) is now modeled as deployment flow stages. The 8 sub-tasks are all covered by Epics B and C. |
| Doc merge preservation idea | LLM-driven doc merge during rebase | idea | **KEEP** — unchanged. Grows in importance as multi-project worktrees increase merge frequency. No changes needed. |
| Motivation-context idea | Mandatory motivation context | idea | **KEEP** — unchanged. More important now that Shepherd must write deployment flow rationale as part of Definition of Done. Actually becomes enforcement mechanism for flow selection quality. No changes needed to ticket. |
| Epic splitting idea | Epic splitting | idea | **KEEP** — unchanged. Deferred. |
| Scholar-style research-lane idea | Scholar agent | idea | **KEEP** — unchanged. Deferred. |
| CI integration idea | CI integration | idea | **REWRITE BODY** — Becomes: implement `ci-check` executor type for deployment flows. First implementation: GitHub Actions status polling. The old spec (wait-for-CI in merge pipeline) is obsoleted by the Usher model where CI is a deployment stage not a merge prerequisite. |
| YOK-227 | Smoke test integration | idea | **CLOSE** — smoke is a first-class deployment flow stage with `executor: health-check` or `executor: test-suite`. No separate ticket needed. |
| YOK-228 | Deployment audit log rendering | idea | **REWRITE BODY** — Render deployment history view from the new `deployment_events` schema. Old schema is being wiped. New spec: `deployments/log.md` generated from `deployment_events` joined with `deployment_flows` and `items.project`. |
| Manual stage-resume idea | /yoke deploy manual trigger | idea | **REWRITE BODY** — Narrow scope: `/yoke usher YOK-N --from-stage {stage}` for re-running a specific deployment stage on an already-merged item. The old "deployment trigger with production gate" is now the Usher's job. |
| Multi-audience release summaries idea | Multi-audience release summaries | idea | **KEEP** — unchanged. Grows in importance with multi-project: Buzz clients want different release notes than internal Yoke dev notes. |
| YOK-333 | Remove dead dual-write bridge | idea | **KEEP** — small cleanup item, any sprint. Unchanged. |
| YOK-407 | Structured Logging Standard | planned | **KEEP, EXPAND SCOPE** — Already planned. Now gains additional requirement: all log entries (`agent_events` table, when it exists) must include `project` field. The "Client Project Framework" sub-scope of YOK-407 is now Epic A+B+C, so that sub-scope should be removed from YOK-407's body and replaced with a reference to the Epics. YOK-407 becomes: Yoke telemetry only (agent_events, anomaly detection, performance metrics for Yoke internals). |
| YOK-431 | Event Registry + Enforcement | ready | **KEEP** — unchanged. Ship in next sprint. No impact from new architecture. |
| YOK-487 | epic_task_files UNIQUE constraint | ready | **KEEP** — unchanged. Ship in next sprint. |
| YOK-492 | find_project_root() worktree resolution | ready | **KEEP** — but note: after multi-project worktrees land, `find_project_root()` becomes more complex (must distinguish Yoke worktrees from external project worktrees). YOK-492 fixes the current bug; a follow-up ticket will handle multi-project awareness. Ship YOK-492 as-is. |
| YOK-493 | ingest-body GitHub sync | ready | **KEEP** — unchanged. But note: for Buzz items, the GitHub sync must go to Buzz's repo (O-13 dependency). YOK-493 can ship without O-13; it will only sync to Yoke's repo for now. |
| YOK-495 | merge-worktree.sh cleanup trap | ready | **KEEP** — unchanged. Ship in next sprint. |
| YOK-498 | agents.md missing 4 agents | ready | **KEEP** — ship as-is. Agent count stays at 11 (Usher is a skill, not an agent). |
| YOK-499 | HC-37 auto-generate known keys | ready | **KEEP** — unchanged. New config keys (base_port for ephemeral envs, etc.) will need to be added to config.example when Epic F lands. YOK-499 makes that automatic. |
| YOK-500 | find_project_root() deduplication | ready | **KEEP** — unchanged. Ship in next sprint. |
| YOK-501 | classify-dirty-files deduplication | ready | **KEEP** — unchanged. Ship in next sprint. |
| YOK-533 | YOK-454 spec contradiction fix | ready | **KEEP** — unchanged. Ship in next sprint. |
| YOK-551 | Doctor HC: epics without simulation record | idea | **KEEP** — unchanged. Deferred. |
| YOK-554 | Conduct session performance | idea | **KEEP** — unchanged. More relevant after multi-project because conduct sessions will be longer. |

---

### PAD ITEMS — Full Disposition

| PAD Item | Disposition |
|----------|-------------|
| **MAJOR GOAL 1: YOK-407 structured logging** | Kept as YOK-407. Scope narrowed — client project framework sub-scope moves to Epics A-G. See YOK-407 note above. |
| **MAJOR GOAL 2: Multi-project structure** | Fully covered by Epics A–G. Remove from PAD's "MAJOR GOALS" section and replace with reference to the Master Plan. |
| **MAJOR GOAL 3: Integrate with Buzz** | Covered by Epic E. A-2 seeds Buzz config. E-1 is the validation item. Remove from PAD major goals. |
| **Ephemeral environments on demand** | Covered by Epic F. Remove from PAD. |
| **Run all test suites / health checks** | Operational note, not a ticket. Keep in PAD as operator runbook. |
| **"duplicate wrapup skipped" error** | File as new ticket. Not covered in master plan. See O-14 below. |
| **Branding: rename to Ouroboros** | **DEAD permanently.** Remove from PAD entirely. Yoke is Yoke. |
| **Stock portfolio ideas** | Unrelated. Remove from PAD (or move to personal notes). |
| **Ouroboros product vision + goals framework** | **KEEP in PAD.** One concrete ticket when ready: "add Strategic Alignment section to PRD template." Deferred. |
| **StrongDM / competitive landscape research** | **KEEP in PAD.** Deferred research item. |
| **Wisdom preservation mechanism** | **KEEP in PAD.** Low priority. Deferred. |
| **Testing harness system for web apps** | Covered by Epics F (ephemeral envs) and G (tester enhancements). Remove from PAD. |
| **TICKET: Project Domain Model** | Superseded by Epic A. Remove from PAD. |
| **TICKET: Ouroboros Dashboard — API Layer** | Superseded by Epic D (Yoke API). The "dashboard" vision (Next.js frontend, client-facing) is vUtopia — still deferred. The API backend is Epic D. Remove old ticket from PAD, add vUtopia to deferral log. |
| **TICKET: Observability Hook Infrastructure** | Already noted as "Superseded by YOK-407." Remove from PAD. |
| **TICKET: Site / Environment Model** | Superseded by Part 2 schema (sites + environments tables). Remove from PAD. |
| **TICKET: Test Registration and Intelligence** | **KEEP in PAD for now.** This is a significant capability (tests table, test_runs table, flakiness scoring, intelligent test selection) that is NOT covered in the master plan. It's more sophisticated than what Epic G covers. Epic G covers "tester can run tests against ephemeral env." Test registration intelligence is a separate capability for a later sprint. Keep full PAD spec. |
| **TICKET: Test Gates and Approval Gates** | Partially covered — `human-approval` executor handles approval gates. Test gates (which test types are required for which risk level) are NOT explicitly covered. The deployment flow selects what runs, but there's no `test_gates` table or `classify-risk.sh`. **KEEP in PAD** as a future capability. Note in deferral log. |
| **TICKET: Change-Risk Classifier** | **KEEP in PAD.** Not covered in master plan. Deferred. |
| **TICKET: Deploy Command and Orchestration** | Superseded by Epics B + C (deployment flows + Usher). Remove from PAD. |
| **TICKET: CDK Infrastructure Template Library** | **KEEP in PAD.** Deferred to 6-month horizon. Now explicitly positioned as "one capability provider type among many" not the default. |
| **TICKET: Anomaly-to-Ticket Pipeline** | **KEEP in PAD.** Depends on YOK-407 (agent_events table). Deferred. |
| **TICKET: Push-Based Ouroboros Loop** | **KEEP in PAD.** Depends on YOK-407. Deferred. |
| **TICKET: Scenario Validation Framework** | **KEEP in PAD.** Deferred. More valuable after multi-project operation. |
| **TICKET: Active Pattern Propagation** | **KEEP in PAD.** Deferred. Depends on scenario framework. |
| **TICKET: First External Client Project** | Covered by Epic E (Buzz validation). Remove from PAD — Buzz IS the first external client project. |
| **ouroboros.dev website** | **KEEP in PAD.** Long-term. Not blocking anything. |

---

### NEW TICKETS FROM THIS AUDIT

These are net-new tickets identified in this section that were not in the original plan:

| ID | Title | Priority | Depends on |
|----|-------|----------|------------|
| O-1 | ouroboros_entries.project column + ouroboros-db.sh --project flag | Medium | A-1 |
| O-2 | release_entries.project column + filter support in release-notes SKILL.md | Medium | A-1 |
| O-3 | tracks.project column + compose enforcement + conduct track-level project resolution | High | A-1, B-4 |
| O-4 | Multi-project health checks for doctor.sh (10 new HCs) | Medium | A-1, B-3, F-1 |
| ~~O-5~~ | ~~Add Usher to agents.md~~ | — | **DROPPED** — Usher is a skill, not an agent |
| O-6 | Update commands.md for usher + approve + conduct changes | Low | C-3, C-4 |
| O-7 | Rebuild db-reference.md for all new tables and columns | High | All schema tickets |
| O-8 | Update state-management.md + session.md + CLAUDE.md for new post-merge lifecycle | Medium | C-5 |
| O-9 | Update worktree-lifecycle.md for external project worktrees | Medium | A-3 |
| O-10 | done-transition.sh deployment flow guard | High | B-3, C-5 |
| O-11 | Update weave SKILL.md to invoke Usher after each merge | High | C-3 |
| O-12 | Update standup + status SKILL.md for deployment pipeline state | Low | B-3 |
| O-13 | Per-project GitHub repo config (github_repo_url on projects table) | Medium | A-1 |
| O-14 | Fix "duplicate wrapup skipped" error in /yoke wrapup | Low | None |
| O-15 | YOK-407 body update: remove client project framework sub-scope, add project field requirement to agent_events | Low | None (before YOK-407 ships) |

---

## 10.4 — Updated Deferral Log Additions

The following items from the PAD audit are explicitly deferred and added to the deferral log in Part 7:

| Feature | Deferred to | Reason |
|---------|-------------|--------|
| Test registration intelligence (tests table, test_runs, flakiness scoring) | Sprint 4+ | Needs ephemeral envs and tester enhancement first. Sophisticated capability. |
| Test gates table + change-risk classifier | Sprint 4+ | Deployment flows handle the "what runs" question for now. Risk classification is a sophistication layer. |
| Test Gates and Approval Gates (PAD ticket) | Sprint 4+ | Human-approval executor covers the approval gate use case. Formal gate config is an optimization. |
| CDK infrastructure template library | 6-month horizon | No AWS-native projects yet. Confirmed. |
| Anomaly-to-ticket pipeline | After YOK-407 ships | Needs agent_events table. |
| Push-based ouroboros loop | After YOK-407 ships | Needs system_events table. |
| Scenario validation framework | After Epic E validates | Needs real multi-project operation. |
| Active pattern propagation | After scenario framework | Needs scenario validation to be meaningful. |
| ouroboros.dev website | Long-term | Not blocking anything. |
| vUtopia operator dashboard (Next.js frontend) | Phase 2 of business | API (Epic D) must exist and stabilize first. |
| Per-project BOARD-{project}.md | After multi-project validated | Board column changes (Part 2) first. |
| rename Yoke → Ouroboros | Never | Yoke is Yoke. Removed from PAD. |


---

---

# PART 11 — OPEN QUESTIONS RESOLVED

All open questions from Part 9 plus questions surfaced during the Q&A session. Each has a final decision and the document sections it affects.

---

## Q1: How does the Usher get invoked after conduct merges?

**Decision:** Usher is a first-class operator-invoked skill, exactly like every other skill in the chain.

```
/yoke idea
/yoke shepherd
/yoke compose
/yoke conduct
/yoke weave
/yoke usher
```

Operator runs `/yoke usher` after weave completes. Usher reads all items at `status=merged`, runs each through its deployment pipeline, halts on gates or capability gaps, reports results. If a human-approval gate is hit, item sits at `awaiting-approval`, operator approves and re-runs `/yoke usher` to resume from that stage.

**Conduct does not invoke Usher.** Weave does not invoke Usher. Done-transition happens inside Usher when `deploy_stage=complete`.

**Affects:** Part 3 (Usher invocation spec), Part 4 (Shepherd changes), Part 5 (Conduct changes — remove Usher invocation from post-merge step), C-5 ticket spec, O-11 (weave SKILL.md — no Usher invocation needed, drop this ticket).

---

## Q2: Who is authoritative for deployment flow selection?

**Decision:** The deployment flow is a field within the Definition of Done. It is written by the Shepherd during `idea_to_defined` and is subject to review and update by every agent that subsequently touches the item.

- Shepherd writes initial flow selection with rationale as part of DoD
- Boss verdict validates flow is selected (missing = NOT_READY)
- Compose vetting can flag mismatches
- Conduct confirms or updates at dispatch time based on technical plan and Architect's file list
- Engineer flags scope changes during implementation if diff materially differs from spec
- Usher validates at runtime — if flow looks wrong for what actually merged, halts and reports mismatch

The flow field on the item is a live artifact. Any agent can update it with a rationale. Audit trail lives in `shepherd_verdicts`, `conduct_progress`, and `deployment_events`.

**Affects:** Part 4 (Shepherd changes — confirmed), B-4 ticket spec (confirmed), conduct SKILL.md update (add flow re-evaluation step before dispatch and before merge).

---

## Q3: Are tracks strictly project-homogeneous?

**Decision:** Sprints are per-project. Tracks inherit project from sprint. Homogeneity is enforced at the sprint level.

- `sprints` table gets `project TEXT NOT NULL REFERENCES projects(id)`
- `/yoke compose` requires project selection as its first step
- Only items from the selected project are visible during ARRANGE phase
- Tracks have no separate `project` column — they inherit from sprint
- Doctor HC: sprint with items from mixed projects is a data integrity error
- Multi-project sprints are a future advanced capability, explicitly deferred

**Affects:** Part 2 (data model — add project to sprints table, remove project from tracks table), O-3 ticket (rewrite — tracks.project column is dropped, replaced by sprints.project), compose SKILL.md (add project selection as step 0).

---

## Q4: Credential storage for capability configs

**Decision:** Credentials are never stored in the DB. Capability config stores path references to credential files that live outside repos on the local filesystem.

- Non-secret fields (host, user, region, base_port) stored as JSON capability settings
- Secret fields store paths: `{"key_path": "~/.ssh/id_rsa", "env_file": "~/buzz-secrets/.env"}`
- The `secret: bool` flag on capability template config keys marks which fields are path references vs plain values
- Executors resolve paths at runtime — SSH executor reads the key at the path, docker-compose gets `--env-file` pointing to the secrets file
- No OS credential store, no encryption, no new infrastructure for v1
- Revisit when Yoke moves to a remote server

**Affects:** Part 2 (capability_templates seed data — update descriptions to clarify secret fields store paths), Part 3 (executor scripts — resolve paths at runtime), Part 9 open question 5 (closed).

---

## Q5: Deployment failure behavior — requeue vs halt

**Decision:** All deployment failures halt for v1. No requeue.

- Every stage failure sets item to a failed state visible on the board
- Operator makes the judgment call: fix the code (re-shepherd), fix infrastructure (update capability config), or cancel
- `on_failure: requeue` stays in the schema as a future capability but no executor uses it
- Automation of failure recovery patterns deferred until real failure modes are understood from production operation

**Affects:** Part 3 (Usher state machine — remove requeue branch from failure handling for v1, note as future), deployment_flows seed data (set all `on_failure` to `halt`), executor scripts (only two exit codes needed for v1: 0=pass, 1=fail; 2=needs-capability, 3=awaiting-approval remain).

---

## Q6: GitHub issue location for external project items

**Decision:** All items sync to Yoke's GitHub repo regardless of project.

- Yoke's DB is the system of record; Yoke's GitHub repo is the issue tracker for everything Yoke manages
- Buzz items get a `project:buzz` label in Yoke's GitHub repo for filterability
- No per-project GitHub repo config needed
- O-13 ticket (per-project GitHub repo config) is dropped

**Affects:** Part 10 (O-13 — drop this ticket), resync SKILL.md (no changes needed for multi-project), sync-to-github.sh (add project label on creation, no other changes).

---

## Q7: Deployment flow updates when item scope changes

**Decision:** Continuous responsibility across the pipeline — no single owner, no single gate.

- Conduct re-evaluates at dispatch time
- Engineer flags scope changes during implementation
- Usher validates at runtime and halts on obvious mismatches

All three combined. See Q2 for full detail.

---

## Q8: Active sprint — global or per-project?

**Decision:** One active sprint per project. Yoke and Buzz can each have an active sprint simultaneously.

- `sprints` table status constraint changes from "one active globally" to "one active per project" (UNIQUE on project WHERE status='active')
- Board shows both active sprints
- `/yoke conduct` and `/yoke weave` require project context to know which active sprint to operate on
- `/yoke standup` shows state for all active sprints

**Affects:** Part 2 (sprints table — add UNIQUE(project) WHERE status='active' constraint), compose SKILL.md, conduct SKILL.md, weave SKILL.md, standup SKILL.md, rebuild-board.sh.

---

## Q9: Usher invocation from weave (O-11)

**Decision:** Drop O-11. Weave does not invoke Usher. Usher is operator-invoked as a separate skill. See Q1.

---

## Summary of Document Changes Required

| Section | Change |
|---------|--------|
| Part 2 — sprints table | Add `project TEXT NOT NULL REFERENCES projects(id)`, add unique active-per-project constraint |
| Part 2 — tracks table | Remove `project` column (homogeneity via sprint, not track) |
| Part 2 — capability_templates | Clarify secret fields store path references, not values |
| Part 2 — deployment_flows seed | Set all `on_failure` to `halt` |
| Part 3 — Usher state machine | Remove requeue branch, note as future |
| Part 3 — Usher invocation | Operator-invoked skill, not conduct-invoked |
| Part 5 — Conduct post-merge | Remove Usher invocation step; conduct sets status=merged and stops |
| Part 6 — C-5 ticket | Remove "conduct invokes Usher" spec; conduct just sets merged |
| Part 6 — O-3 ticket | Rewrite: tracks.project dropped, sprints.project is the enforcement point. Ticket becomes: add project to sprints table + compose project selection step |
| Part 6 — O-11 ticket | Drop entirely |
| Part 6 — O-13 ticket | Drop entirely |
| Part 7 — Deferral log | Add: requeue failure recovery, multi-project sprints, per-project GitHub sync |
| Part 9 — Open questions | All closed |
| Part 10 — Affected tickets | Update O-3, drop O-11, drop O-13 |


---

---

# PART 12 — README UPDATE SPECIFICATION

This part is a complete change spec for `yoke/README.md`. Every section is addressed — intro, diagrams, tables, and prose. Changes are organized by section in document order. Where the change is a full rewrite, the new text is provided. Where it's a targeted edit, the exact location and change are described.

The implementing agent must read this section alongside Part 11 (resolved questions) before making any changes.

---

## 12.1 — Header and Intro Paragraph

**Current:**
> Yoke turns ideas into shipped, deployed, verified code through a disciplined pipeline: spec → plan → parallel execution → merge → deploy → smoke test. Eight specialized subagents do the work.

**Change:** Replace the intro paragraph entirely.

**New text:**
> Yoke turns ideas into shipped, deployed, verified code through a disciplined pipeline: spec → plan → parallel execution → merge → usher → production. Eight specialized subagents and the Usher skill do the work. SQLite holds all state. Git worktrees give you conflict-free parallelism. You make every decision that matters. The AI executes.
>
> Yoke manages multiple projects simultaneously. Each project has its own repo, its own deployment flows, its own environments. Yoke itself is one project. Buzz — or any other app you point Yoke at — is another. One sprint, one board, one learning loop per project.

**Current orchestration tier summary:**
> - **Shepherd** — takes a single item from idea to ready (spec → quality gate → plan → quality gate)
> - **Composer** — assembles a sprint from items at any stage, shepherds them all to ready, evaluates the whole plan, materializes it
> - **Conduct** — executes a track of sprint items autonomously (sync → engineer → test → simulate → merge → deploy → smoke test)

**Change:** Add Usher and update Conduct description.

**New text:**
> - **Shepherd** — takes a single item from idea to ready (spec → quality gate → plan → quality gate)
> - **Composer** — assembles a sprint from items at any stage, shepherds them all to ready, evaluates the whole plan, materializes it. **Requires project selection — each sprint belongs to exactly one project.**
> - **Conduct** — executes a track of sprint items autonomously (sync → engineer → test → simulate → merge)
> - **Usher** — guides merged items through the deployment pipeline to production (deploy → verify → smoke → done)

---

## 12.2 — Table of Contents

**Change:** Add Usher section entry. Update "The Conduct" entry subtitle to remove "deploy → smoke test" (now owned by Usher).

**Add after "The Conduct — Sprint Execution":**
> - [The Usher — Deployment Pipeline](#the-usher--deployment-pipeline)

**Add after "Deployment environments" in Item Lifecycle:**
> - [Deployment Flows](#deployment-flows)

---

## 12.3 — Master Flowchart

**Change:** The master flowchart must be redrawn. Current flowchart ends at "SPRINT DONE — all items smoke tested on target environment." The new flowchart has SPRINT DONE split across two phases: Conduct completes at MERGED, Usher takes over for delivery.

**Replace the entire ASCII diagram** with:

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  IDEA CAPTURE                                                                       │
│  /yoke idea "title"  →  YOK-N, status=idea  →  SQL + backlog/{N}.md              │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │
                                       │  items accumulate in backlog
                                       ▼
                    ┌──────────────────────────────────────────────────────────────────┐
                    │  SHEPHERD (per item: idea → ready)                               │
                    │  Scholar → PM → Boss → [Designer → Boss] →                      │
                    │  [Architect → Simulator → Boss]                                 │
                    │  Writes Definition of Done including deployment flow selection   │
                    └──────────────────────────────┬───────────────────────────────────┘
                                                   │
                    ┌──────────────────────────────▼───────────────────────────────────┐
                    │  COMPOSER (sprint-level: project-scoped sprint planning)         │
                    │  Select project → COMPOSE → FINAL BOSS → SHEPHERD →             │
                    │  FINAL BOSS → MATERIALIZE                                        │
                    │  → "Launch conducts: /yoke conduct T1..TN"                  │
                    └────────────────────────────────┬─────────────────────────────────┘
                                                     │
                              user launches N parallel sessions
                                                     │
           ┌─────────────────────────────────────────┼────────────────────────────────┐
           │                                         │                                │
   ┌───────▼────────────────┐       ┌────────────────▼──────────────┐  ┌─────────────▼────────────┐
   │ CONDUCT T1           │       │ CONDUCT T2                  │  │ CONDUCT T3             │
   │                        │       │                               │  │                          │
   │ For each item:         │       │ (same pipeline)               │  │ (same pipeline)          │
   │  SYNC → ENGINEER →     │       │                               │  │                          │
   │  TEST → SIMULATE       │       │                               │  │                          │
   │  → MERGE               │       │                               │  │                          │
   │  → status=merged       │       │                               │  │                          │
   └───────────┬────────────┘       └────────────────┬──────────────┘  └─────────────┬────────────┘
               │                                     │                               │
               └─────────────────────────────────────┼───────────────────────────────┘
                                                     │
                                                     │  all items at status=merged
                                                     ▼
                    ┌────────────────────────────────────────────────────────────────┐
                    │  /yoke weave  →  batch merge coordination                    │
                    └──────────────────────────────┬─────────────────────────────────┘
                                                   │
                                                   ▼
                    ┌────────────────────────────────────────────────────────────────┐
                    │  USHER (/yoke usher)                                         │
                    │                                                                │
                    │  For each merged item:                                         │
                    │    Read deployment flow from item's Definition of Done         │
                    │    Execute stages sequentially:                                │
                    │      staging-deploy → staging-verify → regression →           │
                    │      review [human gate] → prod-deploy → smoke → complete     │
                    │                                                                │
                    │  Halts on:                                                     │
                    │    needs-capability  🔑  → operator configures, re-run usher  │
                    │    awaiting-approval ⏳  → /yoke approve, re-run usher      │
                    └──────────────────────────────┬─────────────────────────────────┘
                                                   │
                                      ┌────────────▼─────────────┐
                                      │     SPRINT DONE          │
                                      │  all items status=done   │
                                      │  deploy_stage=complete   │
                                      └──────────────────────────┘
```

---

## 12.4 — Core Concepts: Item Types

**No change needed.** Issue/Epic/Task taxonomy is unchanged.

---

## 12.5 — Core Concepts: The Subagent Roster

**Change:** Add Usher to the Orchestrators table. Update Conduct description. Update agent count in the intro sentence.

**Current intro:**
> Eight subagents organized into three tiers

**New:**
> Eight subagents organized into three tiers (plus orchestration skills and the Usher skill)

**Current Orchestrators table:**

| Agent | Role | Scope |
|---|---|---|
| Shepherd | Item-level pipeline | Single item |
| Compose | Sprint-level pipeline | Entire sprint |
| Conduct | Track-level execution: sync → engineer → test → simulate → merge → deploy → smoke test | One track of a sprint |

**New Orchestrators table:**

| Agent | Role | Scope |
|---|---|---|
| **Shepherd** | Item-level pipeline: idea → ready through all quality gates | Single item |
| **Composer** | Sprint-level pipeline: compose → shepherd → evaluate → materialize. **Project-scoped — each sprint is one project.** | Entire sprint |
| **Conduct** | Track-level execution: sync → engineer → test → simulate → merge | One track of a sprint |
| **Usher** | Deployment pipeline: guide merged items through deployment flow to production. Halts on capability gaps and approval gates. | All merged items in a project |

---

## 12.6 — Item Lifecycle

### Status table

**Change:** Replace the current 10-status table. The statuses `qa` and `done` need updating. Add `merged`, `needs-capability`, `awaiting-approval`. Remove the old `qa` status (it was doing double duty — the concept now splits across `review` and the deployment pipeline stages).

**New status table:**

| Status | Meaning | Transition | Gate |
|--------|---------|------------|------|
| `idea` | Captured but not fleshed out | `/yoke idea` | — |
| `defined` | Spec written, Boss-approved, deployment flow selected | PM writes spec → Boss evaluates | Boss: READY / NOT READY / CAVEATS |
| `designed` | UX spec written, Boss-approved (optional) | Designer writes UX → Boss evaluates | Boss: READY / NOT READY / CAVEATS |
| `planned` | Architect plan written, Boss-approved (epics) | Architect plans → Simulator checks → Boss evaluates | Boss: READY / NOT READY / CAVEATS |
| `ready` | All gates passed, eligible for execution | Shepherd completes | — |
| `active` | Code in progress | Conduct | — |
| `passed` | Engineer + Tester + Simulator passed | Conduct (all gates clear) | — |
| `merged` | Code merged to main, Usher has not yet completed | `merge-worktree.sh` sets this; Usher takes over | — |
| `needs-capability` 🔑 | Usher halted — missing or misconfigured infrastructure capability | Usher executor exit code 2 | Operator configures capability, re-runs `/yoke usher` |
| `awaiting-approval` ⏳ | Usher halted — human approval gate reached | `human-approval` executor | `/yoke approve YOK-N`, then re-run `/yoke usher` |
| `done` | Deployment pipeline complete, code verified in production | Usher sets when `deploy_stage=complete` | — |
| `cancelled` | Explicitly cancelled | Manual | — |

**Important:** `deploy_stage` is a parallel tracking field on the item that shows current position within the deployment pipeline after merge. It is not the same as `status`. An item at `status=merged` may have `deploy_stage=staging-deploy` or `deploy_stage=regression` etc. The board shows both.

### What "done" means

**Change:** Update the "What done means" section.

**New text:**
> `done` is not "code is merged." `done` is "code has completed the full deployment pipeline and is verified in the target environment." Two parallel tracks converge to produce `done`:
>
> - **Pre-merge (Conduct's responsibility):** code is reviewed, tested, simulated, and merged. Status becomes `merged`.
> - **Post-merge (Usher's responsibility):** the deployment flow executes — staging deploy, regression testing, human approval, production deploy, smoke tests. When the final stage completes, `deploy_stage=complete` and `status=done`.
>
> For items with an `internal` deployment flow (Yoke scripts, docs, config changes), the Usher completes immediately — merge and done are effectively simultaneous. For items targeting a deployed application, the gap between `merged` and `done` may span minutes (automated pipeline) or days (human approval gate).

### Lifecycle comparison diagram

**Change:** Update the diagram to replace `→ done` at the end with `→ merged → [usher pipeline] → done`.

**New diagram:**
```
ISSUE:  idea ─── defined ─── [designed] ──────────── ready ── active ── passed ── merged ──[usher]── done
                 ↑PM+Boss     ↑Designer+Boss                  ↑conduct  ↑tester   ↑merge   ↑usher    ↑complete

EPIC:   idea ─── defined ─── [designed] ── planned ── ready ── active ── passed ── merged ──[usher]── done
                 ↑PM+Boss     ↑Designer+Boss ↑Arch+Sim+Boss   ↑conduct  ↑conduct  ↑merge   ↑usher    ↑complete

TASK:                                                 ready ── active ── review ── done
                                                               ↑dispatch  ↑tester   ↑dispatch
```

### Deployment environments section

**Change:** Replace the current `deploy_envs` config-based deployment section with the new deployment flows model. This is a full rewrite.

**New section title:** "Deployment Flows"

**New text:**
> Every item that results in deployed code has a **deployment flow** selected during shepherding and recorded in its Definition of Done. The flow defines the exact sequence of stages that must complete before the item is `done`.
>
> Flows are named, per-project, and configured in the `deployment_flows` table. Each project has a library of flows for different change types:
>
> | Flow | When used | Stages |
> |------|-----------|--------|
> | `internal` | Scripts, docs, config — no deployment | merged → complete |
> | `buzz-prod-hotfix` | Urgent prod fix | merged → prod-deploy → smoke → complete |
> | `buzz-prod-release` | Standard Buzz feature | merged → staging-deploy → staging-verify → regression → review → prod-deploy → smoke → complete |
>
> **Stage executor types** define how each stage runs:
>
> | Executor | What it does |
> |----------|-------------|
> | `auto` | No-op, advance immediately |
> | `deploy-command` | Run the project's deploy script for a named environment |
> | `health-check` | HTTP GET against environment URL, expect 2xx |
> | `test-suite` | Run a named test suite (maps to project's test commands) |
> | `adaptive-e2e` | Playwright + screenshot + LLM fallback for complex UI testing |
> | `human-approval` | Halt and wait for `/yoke approve YOK-N` |
> | `script` | Run an arbitrary shell command |
>
> **Failure behavior:** All stage failures halt the pipeline for v1. The item sits at a failed stage on the board. The operator diagnoses, fixes, and re-runs `/yoke usher YOK-N` to resume. Automated recovery is a future capability.

### Sprints section update

**Change:** Update the sprints description to reflect per-project active sprints.

**Current:**
> Only one sprint can be active at a time.

**New:**
> One sprint can be active per project at a time. Yoke and Buzz can each have an active sprint running simultaneously. Sprints are project-scoped — a Yoke sprint contains only Yoke items; a Buzz sprint contains only Buzz items. The `/yoke compose` command requires project selection as its first step.

---

## 12.7 — The Shepherd Section

**Change:** Add one paragraph to "What the Shepherd does" covering the new deployment flow selection step.

**Add after the existing description:**
> The Shepherd also determines the item's **deployment flow** during `idea_to_defined` — writing a "Definition of Done" section into the item body that specifies the project, site (if applicable), selected flow, and rationale. This selection is reviewed and can be updated by the Boss, the Compose during vetting, and the Conduct at dispatch time if the actual scope differs from the spec.

---

## 12.8 — The Compose Section

**Change:** Add project selection as the first step of the five-phase description.

**Current:**
> **The five phases:**
> ```
> COMPOSE → FINAL BOSS (pre) → SHEPHERD → FINAL BOSS (post) → MATERIALIZE
> ```

**New:**
> **The six phases:**
> ```
> SELECT PROJECT → COMPOSE → FINAL BOSS (pre) → SHEPHERD → FINAL BOSS (post) → MATERIALIZE
> ```
>
> **SELECT PROJECT** — `/yoke compose` requires selecting a project as its first step. Only items from the selected project are eligible for this sprint. One active sprint per project is allowed simultaneously.

---

## 12.9 — The Conduct Section

**Change:** Multiple targeted updates.

**1. Opening description — remove deploy and smoke test from Conduct's scope.**

**Current:**
> The Conduct owns an entire track of the active sprint... One Conduct per track; tracks run in parallel across tabs.

**Add sentence:**
> The Conduct's responsibility ends at `status=merged`. Post-merge delivery is owned by the Usher.

**2. Per-item flow diagram — update the end of the diagram.**

The diagram currently ends at:
```
│  SMOKE TEST (per item on target env)             │
│  PASS → phase = smoke_tested → SQL. Item done.   │
│  FAIL → BLOCKED (stop, needs human diagnosis)    │
└──────────────────────────────────────────────────┘
│
┌──────────────────────────────────────────────────┐
│  TRACK COMPLETE ✓                                │
│  All items smoke tested on target env            │
└──────────────────────────────────────────────────┘
```

**Replace with:**
```
│  MERGE (all items, in track order)              │
│  For each item:                                 │
│    Trial merge → PR → CI gate → merge           │
│    status = merged → SQL                        │
│    Conflicts? → auto-resolve or fallback        │
│    Unresolvable? → BLOCKED (stop)               │
└──────────────────────────────────────────────────┘
│
┌──────────────────────────────────────────────────┐
│  TRACK COMPLETE ✓                                │
│  All items at status=merged                      │
│  Run /yoke usher to complete delivery          │
└──────────────────────────────────────────────────┘
```

**3. "When the Conduct stops" section — update.**

Remove references to deploy failures and smoke test failures as Conduct stop conditions. These are now Usher stop conditions.

**New text:**
> The Conduct stops and returns when it can't proceed autonomously during the pre-merge phases. On stop, it writes `phase=blocked` + `blocked_reason` to SQL. Stop conditions: Engineer→Tester loop exhausts retries, Simulator finds architectural gaps requiring design decisions, merge conflict needs manual resolution, CI fails. Post-merge failures (deploy, smoke test) are the Usher's domain and produce `needs-capability` or `awaiting-approval` item states, not Conduct blocked state.

**4. Deploy configuration section — remove entirely.**

The `deploy_envs` config block is replaced by the deployment flows model (covered in the new Item Lifecycle "Deployment Flows" section and the new Usher section). Remove the entire "Deploy configuration" subsection from the Conduct section.

---

## 12.10 — New Section: The Usher — Deployment Pipeline

**Add after "The Conduct — Sprint Execution" section.** This is entirely new content.

```markdown
## The Usher — Deployment Pipeline

The **Usher** guides merged items through the deployment pipeline to production. It is a first-class orchestration skill, invoked by the operator after `/yoke weave` completes.

```
/yoke idea
/yoke shepherd  
/yoke compose
/yoke conduct
/yoke weave
/yoke usher      ← delivery
```

### What the Usher does

Given a set of items at `status=merged`, the Usher reads each item's selected deployment flow and executes the stages in sequence. For each stage, it dispatches the appropriate executor script, records the result to `deployment_events`, and advances `deploy_stage`. When the final stage (`complete`) passes, the item's `status` becomes `done`.

**Stateless invocation, stateful DB.** The Usher can be re-run at any time. It reads `deploy_stage` from the DB and picks up from where it left off. A session that crashes mid-pipeline is resumed by re-running `/yoke usher`.

### Halt conditions

The Usher halts and exits cleanly when it encounters:

| Condition | Item state | How to resume |
|-----------|-----------|---------------|
| Missing capability 🔑 | `needs-capability` | Configure the capability (credentials, env config), then re-run `/yoke usher` |
| Human approval gate ⏳ | `awaiting-approval` | Run `/yoke approve YOK-N [--note "..."]`, then re-run `/yoke usher` |
| Stage failure | `{stage}-failed` | Diagnose the failure, fix the root cause, then re-run `/yoke usher` |

All failures halt for v1 — the Usher never automatically retries or reroutes. This is intentional: deployment failures in production deserve human judgment, not automated recovery.

### Deployment flows

Each project configures a library of named deployment flows. The Shepherd selects the appropriate flow for each item during definition. Examples:

```
yoke-internal     → merged → complete
                      (internal scripts/docs — no deployment needed)

yoke-api-deploy   → merged → api-restart → health-check → complete
                      (restart local FastAPI process)

buzz-prod-release → merged → staging-deploy → staging-verify →
                      regression → review [human] → prod-deploy → smoke → complete

buzz-prod-hotfix         → merged → prod-deploy → smoke → complete
```

### Capability self-invention

When the Usher's executor encounters a capability it needs but isn't configured — a new deployment mechanism, an infrastructure type it hasn't seen before — it defines the capability template on the spot and asks the operator for the required credentials or config. The template is saved to the `capability_templates` table and is available for any future project.

```
⛔ CAPABILITY NEEDED: ephemeral-env
Item YOK-412 is halted at stage staging-deploy.

Required: ephemeral environment spin-up capability
Config needed:
  - base_port: base port for this project's ephemeral environments
  - compose_file: path to docker-compose file
  - env_file: path to secrets file (outside repo)
  - startup_timeout_s: seconds to wait for health check

Once configured, run: /yoke usher YOK-412 to resume.
```

### Running the Usher

```bash
/yoke usher              # Process all merged items across all projects
/yoke usher --project buzz  # Only Buzz items
/yoke usher YOK-412      # Single item (resume from current deploy_stage)
/yoke approve YOK-412 --note "Looks good on staging"
/yoke usher YOK-412      # Resume after approval
```
```

---

## 12.11 — Command Reference

**Changes:**

**1. Primary entry points table — add Usher, update Conduct.**

| Command | Change |
|---------|--------|
| `/yoke compose` | Add note: "Requires project selection. Scopes sprint to one project." |
| `/yoke conduct T{N}` | Update purpose: "Execute a track autonomously: sync → engineer → test → simulate → merge. Delivery handled by Usher." |
| Add `/yoke usher [YOK-N]` | "Execute deployment pipeline for merged items. Resumes from current `deploy_stage`. Halts on capability gaps and approval gates." |
| Add `/yoke approve YOK-N` | "Approve a human gate for an item at `awaiting-approval`. Enables Usher to resume." |

**2. Maintenance table — update `/yoke deploy`.**

Current: `/yoke deploy YOK-N --env <env>` — Manual deployment trigger.

**Replace with:** `/yoke usher YOK-N --from-stage {stage}` — Re-run a specific deployment stage on an already-merged item.

**3. System internals table — update conduct description.**

Remove "deploy → smoke test" from conduct description. Add note that conduct ends at merge.

---

## 12.12 — Architecture: SQL as State Bus

**Change:** Update the tables reference table.

**Current `deployment_events` row:**
> Per-item, per-env, per-step deployment pipeline | Conduct

**New:**
> Per-item, per-stage deployment pipeline results | Usher

**Add new rows:**

| Table | Purpose | Writer |
|-------|---------|--------|
| `projects` | Multi-project registry: repo_path, context files, test commands | `project-db.sh` |
| `deployment_flows` | Named deployment flow definitions per project | `flow-db.sh` |
| `sites` | Site definitions per project | `site-db.sh` |
| `environments` | Environment definitions per site (staging, production, etc.) | `site-db.sh` |
| `project_capabilities` | Configured capability instances per project | `capability-db.sh` |
| `capability_templates` | Capability type definitions (ssh, docker, ephemeral-env, etc.) | `capability-db.sh` |
| `ephemeral_environments` | Active per-branch ephemeral environments | Conduct/Usher |

---

## 12.13 — Architecture: Hooks

**No change needed.** Hook table is not affected by new architecture.

---

## 12.14 — Directory Structure

**Change:** Update the directory listing and the SQL tables in the explanatory text.

**1. Add to `yoke/` listing:**
```
├── docs/
│   └── yoke-current-master-plan.md   # Master plan reference document
```

**2. Add to `.claude/agents/` description:**
> 11 subagent definitions (yoke-*.md)

**3. Add new executors directory:**
```
├── skills/yoke/
│   ├── SKILL.md
│   ├── {command}/SKILL.md
│   └── scripts/
│       ├── executors/          # Usher deployment stage executor scripts
│       │   ├── exec-auto.sh
│       │   ├── exec-deploy-command.sh
│       │   ├── exec-health-check.sh
│       │   ├── exec-test-suite.sh
│       │   ├── exec-human-approval.sh
│       │   └── exec-script.sh
│       └── [other scripts]
```

**4. SQL tables description — add `items.project`, `items.deploy_stage` to the `items` row description:**
> `items` — All item metadata: status, priority, type, sprint, track, body (the spec), **project (FK to projects table), deployment_flow, deploy_stage** | `backlog-registry.sh` via `item-db.sh`

---

## 12.15 — Ouroboros Section

**Change:** Add one sentence clarifying that ouroboros entries are now project-tagged.

**Current:**
> Observations are logged to the `ouroboros_entries` table in `yoke/yoke.db` via `ouroboros-db.sh insert-entry`.

**New:**
> Observations are logged to the `ouroboros_entries` table in `yoke/yoke.db` via `ouroboros-db.sh insert-entry --project {project}`. Entries are tagged with the project being worked on — Buzz reflections are tagged `project=buzz`, Yoke reflections are tagged `project=yoke` — so patterns can be analyzed per-project or across projects.

---

## 12.16 — Configuration Section

**Change:** Replace the `deploy_envs` config example with a note that deployment is now configured via deployment flows in the DB, not via text config keys.

**Current text:**
> ```
> deploy_envs=main
> deploy_steps_main=smoke_test
> ...
> ```

**Replace with:**
> Deployment configuration lives in the `deployment_flows` table in `yoke/yoke.db`, not in the text config file. Each project defines named deployment flows covering the stages items must pass through after merge. Run `/yoke project show {project}` to see configured flows and environments. Run `/yoke usher --help` for deployment pipeline options.
>
> The text config file (`yoke/config`) still holds non-deployment configuration: WIP caps, session timeouts, board art settings, GitHub integration config, and project-level overrides.

---

## 12.17 — FAQ

**Change:** Update and add entries.

**Update: "What's the minimum flow?"**

**Current:**
> `/yoke compose` → `/yoke conduct T1`. Two commands.

**New:**
> `/yoke compose` (select project, feed in ideas) → `/yoke conduct T1` → `/yoke weave` → `/yoke usher`. Four commands from "I have ideas" to "code is in production." For projects with no deployment pipeline (internal scripts), Usher completes in seconds.

**Update: "What if I want to deploy manually?"**

**Current:** `/yoke deploy YOK-N --env <env>` — Manual deployment trigger.

**New:**
> Use `/yoke usher YOK-N` to re-run the deployment pipeline from the beginning, or `/yoke usher YOK-N --from-stage {stage}` to resume from a specific stage. The Usher always reads the item's configured deployment flow — it does not bypass it.

**Add: "Can Yoke manage multiple projects?"**

> Yes. Yoke is multi-project natively. Each project has its own repo, its own deployment flows, its own environments, and its own active sprint. Yoke itself is always one of the projects. Add a new project with `/yoke project create`, configure its capabilities (SSH access, Docker, etc.), define its deployment flows, and Yoke manages it alongside everything else. The board shows all active sprints. The Usher handles all merged items regardless of project.

**Add: "What is a deployment flow?"**

> A named sequence of stages that an item must pass through after merging before it is considered `done`. Each project has a library of flows for different change types — a hotfix flow might go directly to production, a sprint release flow might go through staging, regression testing, human approval, then production. The Shepherd selects the appropriate flow for each item during definition. The Usher executes it.

**Add: "What does needs-capability mean?"**

> The Usher's deployment pipeline reached a stage that requires infrastructure access Yoke doesn't have configured — an SSH key, Docker credentials, a secrets file path, an AWS access key, etc. The item sits at `needs-capability` 🔑 on the board. The Usher printed exactly what's needed. Configure the capability (usually by adding a credential path to the `project_capabilities` table), then re-run `/yoke usher YOK-N` to resume.

**Add: "What does awaiting-approval mean?"**

> The item's deployment flow has a `human-approval` stage and that stage has been reached. The item is paused at ⏳ on the board waiting for your sign-off. Review the changes on staging, then run `/yoke approve YOK-412 --note "Looks good"`. Then re-run `/yoke usher YOK-412` to proceed to production deployment.

**Update: "Does Ouroboros only improve Yoke?"**

**Current:** No. Ouroboros operates on whatever repo Yoke is installed in.

**New:** No. Ouroboros operates on every project Yoke manages. Health checks, simulations, and agent reflections are all project-tagged — learnings from Buzz work stay associated with Buzz, learnings from Yoke internal work stay associated with Yoke. Patterns can surface per-project or across projects.

**Update: "What's the production confirmation gate?"**

**Current:** The last environment in `deploy_envs` always requires explicit human confirmation.

**New:** Any deployment flow stage with `executor: human-approval` requires explicit human sign-off before the Usher proceeds. The standard pattern is to place a `human-approval` stage before production deployment in any flow that targets production. This gate cannot be bypassed — the Usher sets `status=awaiting-approval` and exits. You must run `/yoke approve YOK-N` and then re-run `/yoke usher YOK-N` to continue.


---

---

# PART 13 — DOCUMENTATION EPIC

This part specifies a dedicated Documentation epic that consolidates all doc updates into a single coordinated effort. The scattered O-series doc tickets (O-6, O-7, O-8, O-9) are absorbed into this epic. (O-5 was dropped — Usher is a skill, not an agent.) README and VISION changes from Parts 1 and 12 are also handled here.

**Epic title:** "Documentation refresh — multi-project architecture, Usher skill, new lifecycle"

**Type:** Epic | **Priority:** High | **Target:** Sprint 2 (after schema lands in Sprint 1, before Buzz validation in E-1)

**Rationale:** Every doc file currently describes a Yoke-only, pre-Usher, pre-deployment-flows system. Agents reading stale docs will hallucinate wrong schemas, wrong status values, wrong agent counts, and wrong pipeline steps. This is the same class of problem as YOK-250 (DB schema hallucination) and YOK-336 (stale points references causing SQL errors). Documentation debt at architecture boundaries compounds immediately.

**Dependency:** All Sprint 1 schema tickets (Epic A, Epic B) must be merged before this epic runs. The docs must reflect what's actually in the DB, not what's planned.

---

## Files to Update

### VISION.md (repo root)
Already fully specced in Part 1. See Part 1 for section-by-section rewrites. Summary of changes: 1-month target, API layer, infrastructure strategy, what to avoid (rename is dead).

### yoke/README.md
Already fully specced in Part 12. Summary: new flowchart, Usher section, 8 agents + orchestration skills + Usher skill, status table, deployment flows, multi-project everywhere.

### yoke/docs/OVERVIEW.md
**Current:** "Eight specialized AI subagents." Single-project framing throughout. No mention of deployment flows, Usher, multi-project operation.

**Changes needed:**
- Agent count is eight (YOK-579 removed Shepherd, Composer, Conduct agent wrappers); add Usher to the skills/commands description (not the agent list)
- Add multi-project paragraph: Yoke manages multiple projects. Each project has a repo, deployment flows, environments. Yoke itself is one project.
- Add Usher to the orchestration tier description
- Add `deploy_stage` to the status lifecycle description
- Update "What Yoke Is" opening to reflect new scope
- Update any references to `deploy_envs` config — replace with deployment flows

### yoke/docs/agents.md
**Current:** Lists 8 agents with definitions (YOK-579 removed Conduct, Composer, Shepherd agent wrappers). After YOK-498 ships (Boss/Final Boss verification), Usher still needs to be added as a skill entry.

**Changes needed:**
- Add Usher entry: orchestrator, post-merge delivery, reads deployment flow, executes stages via executor scripts, halts on capability gaps and approval gates, stateless invocation / stateful DB
- Update agent count in intro
- Add note that conduct hands off to Usher at status=merged

**Dependency:** YOK-498 must ship first (adds the 4 missing agents). This task adds only Usher.

### yoke/docs/commands.md
**Current:** Missing usher, approve. `/yoke deploy` description is stale.

**Changes needed:**
- Add `/yoke usher [YOK-N] [--project {id}] [--from-stage {stage}]` entry
- Add `/yoke approve YOK-N [--note "..."]` entry
- Update `/yoke conduct` description: ends at merge, not deploy/smoke
- Update `/yoke deploy` entry: rewrite as `/yoke usher YOK-N --from-stage {stage}` redirect note
- Add `/yoke project` command entry (new from A-1)

### yoke/docs/db-reference.md
**Current:** 1,165 lines. Authoritative DB schema reference — agents read this to avoid hallucinating SQL. Currently missing all new tables and columns. This is the highest-risk stale doc in the system.

**Changes needed (all additive unless noted):**

*New tables to document fully (schema + all columns + writer + example queries):*
- `projects` — full schema, seed data examples, example queries (get by id, list all)
- `deployment_flows` — full schema, JSON stage format, executor types reference, example queries
- `sites` — schema, example queries
- `environments` — schema, UNIQUE constraint, example queries
- `project_capabilities` — schema, JSON config format, secret vs non-secret fields convention
- `capability_templates` — schema, required_config format, requires array
- `ephemeral_environments` — schema, status values, example queries

*Updated tables (new columns):*
- `items` — add `project` (FK), `deployment_flow` (FK), `deploy_stage` (TEXT). Update status values list to include merged, needs-capability, awaiting-approval. Update example queries.
- `ouroboros_entries` — add `project` column after O-1 lands
- `release_entries` — add `project` column after O-2 lands
- `sprints` — add `project` column after O-3 lands

*New deployment_events schema:*
- Full wipe and replace. Document new columns: item, project, flow, stage, executor, result, detail, capability_needed, started_at, completed_at

*Status values section:*
- Update the canonical status list to include all new values
- Add `deploy_stage` as a distinct concept — not a status, but a parallel tracking field

*Agent-facing section (critical for preventing SQL errors):*
- Add: "Items targeting external projects: always include `project` in INSERT and WHERE clauses"
- Add: "Deployment flow selection: read from items.deployment_flow, not from config file"
- Add: "Never set items.status = 'done' directly — this requires YOKE_DONE_TRANSITION=1 env var AND deploy_stage = 'complete' for items with deployment flows"

### yoke/docs/backlog-schema.md
**Current:** YAML frontmatter schema for backlog/{NNN}.md files. Missing new fields.

**Changes needed:**
- Add `project` field to required fields
- Add `deployment_flow` field
- Add `deploy_stage` field (nullable, set post-merge)
- Update HC-16 validation note to include new fields
- Add "Definition of Done" as a required body section for non-internal items

### yoke/docs/state-management.md
**Current:** Describes item status lifecycle ending at `done`. No post-merge pipeline. No `deploy_stage` concept.

**Changes needed:**
- Add `merged` as a distinct status with explanation
- Add `needs-capability` and `awaiting-approval` as halt states
- Add `deploy_stage` section: what it is, when it's set, what values it can hold, how it relates to `status`
- Update the status transition diagram to show post-merge states
- Add Usher ownership section: pre-merge = Conduct, post-merge = Usher
- Add capability self-invention flow: how items reach needs-capability, how operator resolves it
- Add human approval gate flow: how items reach awaiting-approval, how operator approves and resumes
- Update session.md reference note to include new statuses in Always Do First context

### yoke/docs/worktree-lifecycle.md
**Current:** Documents worktree create/use/merge/cleanup phases. Assumes Yoke's own repo as the only target.

**Changes needed:**
- Add new section: "External project worktrees"
  - `create-worktree.sh --project {id}` flag
  - Worktree lands in `{project_repo_path}/.worktrees/YOK-{N}/`
  - Yoke's own scripts remain at Yoke's path — never modified
  - Context bundle injected into engineer prompt includes project identity, AGENTS.md, relevant docs
  - Cleanup: `merge-worktree.sh` resolves project repo_path from items.project
- Update Phase 1 (Create): note that external project worktrees use `--project` flag
- Update Phase 3 (Merge): note that merge-worktree.sh reads items.project to resolve correct repo root
- Add Doctor HC reference: HC for worktrees in wrong location given item's project

### yoke/docs/scripts.md
**Current:** 1,227 lines. Full reference for all shell scripts. Missing all new scripts from the new architecture.

**Changes needed:**

*New scripts to document:*
- `project-db.sh` — project CRUD wrapper (init, create, get, list, update)
- `flow-db.sh` — deployment flow CRUD (init, create, get, list, stages)
- `site-db.sh` — site and environment CRUD
- `capability-db.sh` — capability template and instance CRUD
- `env-db.sh` — ephemeral environment lifecycle (create, update-status, list-active, cleanup-stale)
- `dispatch-context.sh` — context bundle assembly for external project dispatch
- `deploy-pipeline.sh` — Usher's main orchestrator (reads flow, iterates stages, dispatches executors, updates state)
- `restart-api.sh` — Yoke API process restart
- `executors/exec-auto.sh` — no-op stage executor
- `executors/exec-deploy-command.sh` — deploy command executor
- `executors/exec-health-check.sh` — HTTP health check executor
- `executors/exec-test-suite.sh` — test suite executor
- `executors/exec-human-approval.sh` — human approval gate executor
- `executors/exec-script.sh` — arbitrary script executor

*Updated scripts:*
- `create-worktree.sh` — document new `--project` flag
- `merge-worktree.sh` — document that it now sets `status=merged` not `done`, and reads items.project for repo resolution
- `done-transition.sh` — document new deployment flow guard: refuses to run if item has deployment_flow and deploy_stage != 'complete'
- `ouroboros-db.sh` — document new `--project` flag on `insert-entry`
- `release-notes-db.sh` — document new `--project` filter
- `yoke-db.sh` — document new domain wrappers registered in router (project, flow, site, capability, env)
- `rebuild-board.sh` — document new columns: Project, Site, Deploy Stage; emoji markers for halt states

*Remove or note as deprecated:*
- Any references to `deploy_envs` config-driven deployment scripts
- Any references to conduct-owned smoke test scripts (now executor scripts)

### yoke/docs/hooks.md
**Current:** Documents SubagentStop, PostToolUse (Bash), PreToolUse (Write/Edit) hooks.

**Changes needed:**
- Minor: note that `on-bash-complete.sh` (PostToolUse) now handles project-aware progress syncing
- Add note: Usher executor scripts run outside of hooks — they are called by `deploy-pipeline.sh` directly

### yoke/docs/dedup.md
**No change needed.** Dedup system is project-agnostic and unchanged.

### yoke/docs/db-output-format.md
**No change needed.** Output format conventions are unchanged.

### yoke/docs/agent-conventions.md
**No change needed.** Agent invocation conventions are unchanged.

---

## Task Decomposition (for Architect)

Suggested task breakdown — each task is independently completeable and testable:

| Task | Files | Notes |
|------|-------|-------|
| DOC-1 | VISION.md | Apply all Part 1 rewrites |
| DOC-2 | README.md | Apply all Part 12 changes including new flowchart and Usher section |
| DOC-3 | OVERVIEW.md, agents.md, commands.md | Three short files, one task |
| DOC-4 | db-reference.md — new tables | Add all 7 new tables. Highest priority. |
| DOC-5 | db-reference.md — updated tables + status vocab | Update items, ouroboros_entries, release_entries, sprints, deployment_events |
| DOC-6 | backlog-schema.md, state-management.md | Status lifecycle and schema fields |
| DOC-7 | worktree-lifecycle.md | External project worktrees section |
| DOC-8 | scripts.md — new scripts | Document all new scripts from new architecture |
| DOC-9 | scripts.md — updated scripts | Update existing script docs for changed behavior |
| DOC-10 | hooks.md | Minor updates only |

**Acceptance criteria for the epic:**
- No doc file references `deploy_envs` config-based deployment
- All docs show 8 agents (Shepherd, Composer, Conduct are skills; Usher is a skill; all documented in commands.md)
- `db-reference.md` includes all 7 new tables with full schemas
- `state-management.md` includes `merged`, `needs-capability`, `awaiting-approval`, `deploy_stage`
- `commands.md` includes `/yoke usher` and `/yoke approve`
- `worktree-lifecycle.md` includes external project worktree section
- `scripts.md` includes all executor scripts and new domain wrappers
- Doctor HC-5 (doc staleness) passes after all tasks complete

---

## O-Series Tickets Absorbed

The following O-series tickets from Part 10 are absorbed into this epic and should not be filed separately:

- ~~**O-5** (Add Usher to agents.md)~~ — **DROPPED** (Usher is a skill, not an agent)
- **O-6** (Update commands.md) → DOC-3
- **O-7** (Rebuild db-reference.md) → DOC-4 + DOC-5
- **O-8** (state-management.md + session.md + CLAUDE.md) → DOC-6 (session.md and CLAUDE.md are minor, fold into DOC-6)
- **O-9** (worktree-lifecycle.md) → DOC-7

These are removed from the O-series issue list in Part 10. The remaining O-series tickets (O-1, O-2, O-3, O-4, O-10, O-12, O-14, O-15) are still separate issues.

---

# PART 12 — V2 DELTA: GITHUB ACTIONS DEPLOYMENT MODEL

*Added March 2026. Supersedes specific sections of Parts 3, 6, and 8.*

## What Changed

The deployment model for external projects (Buzz) fundamentally changed. Yoke no longer executes deployments directly. GitHub Actions is the execution layer; Yoke is the intelligence layer.

**Yoke's responsibilities:**
- Define deployment pipelines (deployment flows in DB — unchanged)
- Generate and maintain GitHub Actions workflow files in external project repos
- Push branches to external project GitHub repos
- Trigger workflow dispatches via GitHub API
- Poll GitHub Actions API for run status
- Read environment approval state (`waiting` for environment protection gates)
- Update `deploy_stage` and `deployment_events` as workflows progress
- Manage ephemeral environment lifecycle (tracked in Yoke's DB, executed by Actions)

**GitHub Actions' responsibilities:**
- Run test suites (pytest, vitest, playwright)
- Spin up and tear down ephemeral environments
- Deploy to staging and production
- Enforce human approval gates (via GitHub environment protection rules)
- Hold all deployment secrets in GitHub Secrets

## Parts Superseded

| Original Part | Section | Disposition |
|---------------|---------|-------------|
| Part 3 | Executor types table | v1 executor types (`deploy-command`, `test-suite`, `human-approval`, `adaptive-e2e`, `ephemeral-deploy`, `ephemeral-teardown`) cancelled for external projects. Replaced by `github-actions-workflow`. Yoke-internal executors (`auto`, `health-check`, `script`) unchanged. |
| Part 6 | Epic C (Usher) | Superseded → YOK-617 (Usher v2). 6 sub-tickets instead of 5. New: `github-actions.sh`, workflow file management (C-6). Removed: 6 direct executor scripts. |
| Part 6 | Epic F (Ephemeral) | Superseded → YOK-618 (Ephemeral v2). GitHub Actions-based, moved from Sprint 3 to Sprint 2. |
| Part 6 | Epic G (Tester) | Superseded → YOK-619 (Tester v2). Adaptive E2E deferred to Sprint 4+. Replaced by ephemeral URL integration. |
| Part 8 | Sprint 2 sequence | Replaces entirely. Sprint 2 now includes ephemeral environments and GitHub Actions infrastructure. |
| Part 8 | Sprint 3 sequence | Reduced scope: stabilization + structured logging only. |

## New Executor Type: `github-actions-workflow`

```json
{
  "name": "ci-and-staging",
  "executor": "github-actions-workflow",
  "workflow": "buzz-deploy.yml",
  "watch_for": "completed",
  "on_failure": "halt"
}
```

Yoke triggers (or watches, if push-triggered) the specified workflow, polls until `watch_for` state is reached, records result. For stages with environment protection gates, Yoke sees the run pause at `waiting` state, updates `deploy_stage = 'awaiting-approval'`, and resumes polling after human approval in GitHub UI.

## Sprint 2 Pre-Compose Setup — Status Tracker

This section is the authoritative record of what's done vs pending for Sprint 2 setup.

### Phase 1: Ticket Triage — DONE

- [x] YOK-564 (Epic C v1: Usher) → **cancelled** — superseded by YOK-617
- [x] YOK-567 (Epic F v1: Ephemeral) → **cancelled** — superseded by YOK-618
- [x] YOK-568 (Epic G v1: Tester) → **cancelled** — superseded by YOK-619
- [x] YOK-407 (Structured Logging) → **frozen** (Sprint 3)
- [x] YOK-431 (Event Registry) → **frozen** (Sprint 3)

### Phase 2: DB Migrations — DONE

All migrations applied to `yoke.db` AND seed scripts updated for persistence:

- [x] `projects.github_repo TEXT` column — added, buzz = `example-org/buzz`
- [x] `deployment_events.workflow_run_id TEXT` column — added
- [x] `ephemeral_environments` table created (v2 schema with workflow_run_id, github_ref, url)
- [x] `github` capability template added to `capability_templates`
- [x] Buzz `project_capabilities` updated — ssh/docker/ephemeral-env removed, github added
- [x] Buzz `environments` updated — production → github-actions, staging added
- [x] Buzz `deployment_flows` updated — buzz-prod-release and buzz-prod-hotfix use `github-actions-workflow`
- [x] Seed scripts updated: `project-db.sh` (github_repo migration, capability seeds, env seeds, ephemeral_environments CREATE TABLE), `deployment-yoke-db.sh events` (workflow_run_id in CREATE TABLE), `flow-db.sh` (v2 flow stages)

### Phase 3: HC-45 Schema Whitelist — DONE

- [x] `doctor.sh` HC-45 expected schema updated for: projects.github_repo, deployment_events.workflow_run_id, ephemeral_environments table
- [x] `test-doctor-hc45.sh` mock schema updated to match
- [x] All 13 HC-45 tests pass

### Phase 4: New Epic Tickets — DONE

- [x] **YOK-617**: Usher Skill v2 — GitHub Actions deployment pipeline orchestrator (Epic C v2, high priority, GitHub #1405)
- [x] **YOK-618**: Ephemeral Environments v2 — GitHub Actions-based pre-merge validation (Epic F v2, high priority, GitHub #1406)
- [x] **YOK-619**: Tester Agent Enhancements v2 — project-aware testing with ephemeral E2E (Epic G v2, medium priority, GitHub #1407)
- [x] All bodies written with full sub-ticket specs, synced to GitHub
- [ ] **[BOOTSTRAP-TICKET-ID]**: Bootstrap Script — one-time Buzz GitHub Actions setup (issue, high priority)
- [ ] **[ONBOARD-TICKET-ID]**: `/yoke onboard` epic — guided project onboarding command (epic, medium priority, frozen for Sprint 3)

### Phase 5: Documentation Updates — DONE

- [x] Master plan Part 12 appended (this section)
- [x] `db-reference.md` — new columns, tables, executor types, capability templates
- [x] `state-management.md` — executor dispatch, ephemeral lifecycle, v2 halt states
- [x] `commands.md` — usher and approve v2 notes
- [x] `OVERVIEW.md` — USHER phase v2 note
- [x] `CLAUDE.md` — github-actions.sh and env-db.sh in File Layout
- [x] `agents.md` — tester ephemeral URL injection note
- [x] `VISION.md` — updated deployment strategy for GitHub Actions model
- [x] `README.md` — updated deployment flows and Usher sections for v2 model

### Phase 6: Sprint Composition — PENDING

- [ ] Bootstrap ticket ([BOOTSTRAP-TICKET-ID]) must be filed, shepherded, and readied before composition
- [ ] Bootstrap ticket is a prerequisite for YOK-566 (must complete before Buzz validation can begin)
- [ ] Run `/yoke compose` for Sprint 2
- [ ] Assign items to 6 tracks per the track structure below
- [ ] Sprint activated

### Items Already Done (v2 delta listed as open, but completed before this session)

- YOK-570: duplicate wrapup fix — **done**
- YOK-572: ouroboros_entries.project — **done**
- YOK-573: release_entries.project — **done**
- YOK-583: Bash tool truncation in weave — **done**
- YOK-597, 598, 599, 604, 613, 614, 615: All sim-gap items — **done**

## Ticket Mapping

| V1 Ticket | Status | V2 Replacement |
|-----------|--------|----------------|
| YOK-564 (Epic C: Usher) | Cancelled | YOK-617 (Usher v2) |
| YOK-567 (Epic F: Ephemeral) | Cancelled | YOK-618 (Ephemeral v2) |
| YOK-568 (Epic G: Tester) | Cancelled | YOK-619 (Tester v2) |
| YOK-565 (Epic D: Yoke API) | Unchanged | YOK-565 |
| YOK-566 (Epic E: Buzz validation) | Unchanged | YOK-566 |

## Revised Sprint 2 Track Structure

| Track | Items | Dependencies |
|-------|-------|--------------|
| T1: Cleanup | YOK-575, YOK-577, YOK-585 | None |
| T2: GitHub Actions infra | YOK-617 (C-2, C-3, C-4) | None |
| T3: Workflow generation | YOK-617 (C-6) + YOK-618 (F-2, F-4) | T2 |
| T4: Conduct + Tester | YOK-618 (F-1, F-3) + YOK-619 (G-1, G-2) + YOK-617 (C-1) | T2, T3 |
| T5: Yoke API | YOK-565 (D-1, D-2) | T2 |
| T6: Buzz validation | YOK-566 (E-1) | T2, T3, T4 |

## Deferral Log Additions

| Item | Disposition | Reason |
|------|-------------|--------|
| `exec-deploy-command.sh` | Cancelled | GitHub Actions deploys |
| `exec-test-suite.sh` | Cancelled | Tests run inside Actions workflows |
| `exec-adaptive-e2e.sh` (LLM selector repair) | Deferred → Sprint 4+ | Simple E2E failure → engineer fix loop is sufficient |
| `exec-ephemeral-deploy.sh` | Cancelled | Ephemeral envs managed by Actions |
| `exec-ephemeral-teardown.sh` | Cancelled | Teardown by Actions workflow |
| Buzz ssh/docker capability | Cancelled | GitHub Actions holds credentials |
| `/yoke approve` as primary Buzz approval | Reduced scope | GitHub environment protection is primary |

## MVP Scope Constraint

**Do not build any automated failure handling, triage commands, or autonomous recovery logic.** The MVP failure model is:

1. The polling loop syncs GitHub Actions state to Yoke's DB
2. A failed workflow sets the item to a failed `deploy_stage` on the board
3. The operator reads the failure and decides what to do manually

Yoke's job is **accurate state visibility, nothing more**. All sophistication around retry logic, failure categorization, `/yoke triage`, and background LLM activation on failure events is **explicitly deferred** until we have real failure data from a working pipeline.

**Build the polling loop. Sync the state. Show it on the board. Stop there.**

### Explicitly Deferred (do NOT build in Sprint 2)

- Automated retry logic on workflow failure
- Failure categorization / triage commands
- Background LLM activation on failure events
- `/yoke triage` command
- Autonomous recovery flows
- Failure pattern detection

## Open Questions (decide during implementation)

1. Staging environment: dedicated droplet vs same droplet different port vs Fly.io preview?
2. Ephemeral env TTL: tear down on branch delete, after N hours, or both?
3. Usher polling: block and poll (<5 min runs) or exit and ask operator to re-run?
4. Branch push timing: after engineer finishes (recommended) or on worktree creation?
5. Who pushes to main: weave (recommended, owns merge sequence) or conduct?
6. GitHub App repository permissions: full repo access or only workflow dispatch, Actions read, and contents write?

---

# PART 14 — SPRINT 2 PRE-CONDUCT AMENDMENTS

*Source: `yoke/docs/sprint2-preconduct-briefing-final.md` — the design review that identified all issues below.*

This part documents corrections and additions discovered after Sprint 2 tickets were shepherded and readied but before composition and conduct began.

---

## Corrected `buzz-prod-release` Flow Definition

The original `buzz-prod-release` flow included staging stages (`staging-deploy`, `staging-verify`, `regression`) that assumed a staging environment. No staging environment exists for Buzz v1. The corrected v1 flow is:

```
buzz-prod-release: merged (auto) -> prod-deploy (github-actions-workflow, buzz-deploy.yml) -> smoke (github-actions-workflow, buzz-smoke.yml) -> complete (auto)
```

This is a 4-stage flow with two `github-actions-workflow` executor stages:
- **`prod-deploy`** — triggers `buzz-deploy.yml`, which SSHes to the production droplet, rsyncs code, runs `docker compose build && docker compose up -d`. Pauses at the `production` GitHub environment protection gate for operator approval.
- **`smoke`** — triggers `buzz-smoke.yml`, which SSHes to the production droplet and hits health endpoints to verify the deployment succeeded.

The `buzz-prod-hotfix` flow uses the same corrected stages (no staging).

Both `flow-db.sh` seed data and the live DB row were updated to match this definition (see YOK-622 Task 002).

## Bootstrap Requirement

Before the first Buzz conduct session, the following must be set up:

1. **GitHub Secrets** on the Buzz repo: `BUZZ_SSH_KEY`, `BUZZ_SSH_HOST`, `BUZZ_SSH_USER` — credentials for GitHub Actions to SSH to the production droplet.
2. **`production` environment protection** on the Buzz repo — requires at least one reviewer before deployments proceed.
3. **Workflow files** committed to Buzz's main branch: `buzz-deploy.yml` and `buzz-smoke.yml`.

A bootstrap script (`bootstrap-project.sh`) handles steps 1-3 with a preflight check that validates every prerequisite, prints actionable instructions for anything missing, and exits before making changes if any check fails. This ensures zero ambiguity during setup.

## New Tickets

Two new tickets were identified during the design review:

1. **[BOOTSTRAP-TICKET-ID]** — Bootstrap Script: a one-time setup script that wires Buzz into Yoke's GitHub Actions deployment pipeline. Preflight checks 7 prerequisites, creates GitHub Secrets, sets up `production` environment protection, and commits workflow files to Buzz main. Filed as a high-priority issue, prerequisite for YOK-566.

2. **[ONBOARD-TICKET-ID]** — `/yoke onboard` Epic: a guided project onboarding command that generalizes the bootstrap pattern into a reusable workflow for any new project. Filed as a medium-priority epic, frozen for Sprint 3.

Body content for both tickets is prepared in `yoke/docs/pending-tickets/` for the operator to file via `/yoke idea` post-merge.

## First Buzz Validation Item

The first Buzz validation item (YOK-566) specifies docker-compose port override support as its initial validation target. The Buzz docker-compose configuration must support `API_PORT` and `WEB_PORT` environment variables (defaulting to 8000 and 3000 respectively) so that ephemeral environments can run alongside production on the same droplet at offset ports.

## Preflight Requirement

The bootstrap script must include a comprehensive preflight phase that:
- Checks all 7 prerequisites before making any changes
- Prints actionable, step-by-step instructions for anything missing
- Exits with a non-zero code if any check fails
- Makes zero changes until all prerequisites pass

This ensures the operator can run the script, see exactly what needs to be done, do it, and re-run — with zero ambiguity at any step.
