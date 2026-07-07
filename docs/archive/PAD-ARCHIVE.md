> Private operator scratchpad. Not authoritative. Agents should ignore unless explicitly directed.

# Notes

Available domains:
- borgfactory.com
- factoryyoke.com
- yokerush.com
- upyoke.com
- yokesprint.com
- workyoke.com
- sprintyoke.com
- yokeepic.com
- fireyoke.com
- yokeeat.com
- wantyoke.com
- needyoke.com
- letsdoyoke.com
- yokefactor.com
- inayoke.com
- yearofyokes.com
- maniayoke.com
- beastyoke.com
- modelyoke.com

- the MASTER-PLAN.md etc. Strategic Markdown Layer (SML) applies to yoke itself only or also yoke projects?

- another way to express the mission: enable companies to apply the full power of agentic runtimes to run more company with smaller teams

- add capability for a project to use LLM APIs. use in yoke to start moving as many functions as possible completely out of the claude code harness

- abstract the yoke api and yoke-api-deploy flow into a template somehow

- constantly having to tell the agent "for your investigation, use the events table to see exactly what happened"

- after next few epics, make a mster map flowchart of the entire system starting with operator surface and tracing every path through the end of done. include what happens at each step: what is persisted and how; what is read; sub-skill chains invoked; subagents invoked; key tool calls; boss gates; approval gates; merge and deployment procedures etc etc -- intention is for a tersely summarized but highly concise yet comprehensive end to end visual mapping format will be the best way to align on the key gaps and desired evolution over time

---

NON-CLAUDE-CODE HARNESS MANUAL SESSION BOOTSTRAP
## Session Bootstrap — Read These Files First

At the start of every session, read the following files before doing anything else:

1. `CLAUDE.md` — Project rules, code conventions, file layout, hooks, and board docs
2. `.claude/rules/session.md` — Session discipline: work tracking, DB access patterns, tool constraints
3. Run `git log --oneline -10` to see recent commits
4. Run `cat yoke/BOARD.md` to see the current sprint board state

These files define how the project works. Do not write code, create files, or modify state until you have read and internalized them. They contain hard rules (not suggestions) about shell portability, DB access patterns, commit discipline, and project scoping that will cause breakage if ignored.

---

CROSS-MODEL REVIEW

[AT IDEA]
- YOK-XXXX: thoroughly vet this just-entered idea, and make any necessary changes
[AT DEFINED - ISSUE]
- YOK-XXXX: thoroughly vet this just-defined issue, and make any necessary changes
[AT PLANNED - EPIC]
- YOK-XXXX: thoroughly vet this just-planned epic, and make any necessary changes
[AT PASSED]
- YOK-XXXX: thoroughly vet this just-landed ticket in its worktree. make any necessary changes in worktree, and then commit


---

## RUN ALL TEST SUITES

- Run all test suites by launching **one test suite per subagent**, with **up to 5 subagents running at a time**.
- When a subagent returns results, immediately launch the next test suite in a new subagent.

- Instruct each subagent as follows:
  - **Run this test suite and report the results.**
  - If the test suite fails or produces anything other than a perfect **PASS**, investigate the **root cause(s)** thoroughly.
  - Report the full results, including:
    - pass / fail status
    - detailed findings
    - any problems discovered
    - required cleanup
    - root cause(s)
    - any changes made
  - If the issue is **very simple to resolve**, perform the cleanup or fix the root cause and **commit the changes**.

- After all subagent results are collected, **file tickets and apply fixes as warranted**.


## RUN ALL HEALTH CHECKS

- Run all health checks by launching **one health check per subagent**, with **up to 5 subagents running at a time**.
- When a subagent returns results, immediately launch the next health check in a new subagent.

- Instruct each subagent as follows:
  - **Run this health check and report the results.**
  - If the health check fails or produces anything other than a perfect **PASS**, investigate the **root cause(s)** thoroughly.
  - Report the full results, including:
    - pass / fail status
    - detailed findings
    - any problems discovered
    - required cleanup
    - root cause(s)
    - any changes made
  - If the issue is **very simple to resolve**, perform the cleanup or fix the root cause and **commit the changes**.

- After all subagent results are collected, **file tickets and apply fixes as warranted**.

---

FOR SPECIFIC SESSION PROBLEMS:
- problems: [desribe problems]
- file a ticket(s) for the root cause(s) after full investigation, with perfect context for cold start and examples of what happened, after doing all legwork

---
MANUAL /WRAPUP:
[OPERATOR -- DO THIS FIRST]
- look at the events table and the conversation history here and list any problems that occured this session no matter how small down to the smallest failed tool call all the way up to the biggest macro inefficiencies with no actual bugs
[OPERATOR -- DO THIS SECOND -- ACTIVATE PLAN MODE FIRST]
- for all of these issues -- every one: write a plan that lays out what tickets you would file for the root cause(s) after full investigation, with perfect context for cold start and examples of what happened. include full ticket titles and bodies etc in plan.
[OPERATOR -- DO THIS THIRD]
- your job, ALTMAN: carefully vet everything DARIUS came up with, and create your own plan of tickets you'd file, with perfect context for cold starts and examples of what happened, after doing all legwork
 
---
- backup management in yoke. and we need to dogfood with backing up the yoke db because it's not in source. maybe for now we can check in a copy of the db periodically somehow (add health check that commits backup if no backup within last hour lets say)


---

TEMPLATE SYSTEM RULE:
make sure everything follows the pricnple of updating webapp template system in yoke with any changes made to the manifestations of those templates in buzz

---

IF ENGINEER / TESTER LOOP IS STUCK, STOP AGENT AND THEN IN ANOTHER SESSION:
- [YOK-XXXX] is stuck in the eingineer / tester cycle. the agent working on it has been stopped. before doing anything within the ticket implementation process, use this session to first just figure out what the real explanation is -- the core problem, and then validate a solution using a temporary playground.

---
MISSION FOR IDEA->DONE REQUIRING VISUAL QA ON EXTERNAL PROJECT

FIRST:
file a /yoke idea make the buzz login pages theme have a [INSERT THEME] theme -- hereafter THE THEME. go crazy. make items or emojis relating to THE THEME rain down like confetti, 5 seconds after page finishes loading, for a duration of 5 seconds, with each item having a max lifespan of 2s and then disappearing. include qa reqs for multiple VISUAL e2e SCREENSHOT checks:
a. login page theme shows THE THEME theme
b. forgot password page elements all have THE THEME theme as well
c. capture screenshot of THE THEME confetti items falling by taking a screenshot 7 seconds after page loads and verify THE THEME items are visible
**all 3 of these qa reqs must produce screenshots**
**make sure to also insert a requirement to check the related tests at the end of the theme changes, and pre-fix anything that would break, because otherwise tests will fail and energy will be wasted**

SECOND: after filing this idea, advance it to active

THIRD: after it's active, create worktree, seed qa reqs, work the issue, and advance to passed

FOURTH: then usher and auto-approve if ephemeral validation succeeds


---

CONDUCT LITE REAL TIME PLANNING:
- for: [all the current non-done, non-frozen tickets]
    - can these items all be worked in parallel and merged in any order? 
    - give me a clear sequencing plan for max parallelism without problems
    - remember that instructions like "Only include in Wave 1 if it is scoped to docs/state/event design. If it becomes real auto-handoff code, defer it." dont work because the tickets needs to be defined up front and me (the operator) cant inspect those details in flight and dynamically adapt the plan





---











## DEFERRED IDEAS (unfiled from done epics — HC-54 triage 2026-03-10)

### API (from YOK-565)
- Authentication: API key and session-based auth for Yoke API
- Shell script migration: move scripts from direct sqlite3 to API calls
- CORS middleware for cross-origin access
- Rate limiting and request throttling
- WebSocket/SSE for real-time board updates
- API integration tests in CI pipeline

### Deployment Pipeline (from YOK-617)
- Automated retry logic for failed GitHub Actions workflow runs
- Failure categorization and triage commands
- Background LLM activation on deployment failure events
- `/yoke triage` command for deployment failure analysis
- Autonomous recovery flows for deployment pipeline failures
- Failure pattern detection from deployment_events history

### Ephemeral Environments (from YOK-618)
- Multi-project ephemeral environment support (beyond Buzz)
- Resource monitoring and alerting for ephemeral environments

### Tester Agent (from YOK-619)
- Adaptive E2E with LLM-based selector repair for Playwright
- Test intelligence: test registration and execution history tracking
- Playwright screenshot visual regression comparison (LLM-as-judge)

### Track Parallelism (from YOK-635)
- OS-level parallel track execution via session scheduler
- Cross-project track parallelism for multi-project sprints

### Buzz Cleanup (from YOK-670)
- File individual YOK-N backlog items from consolidated Buzz CURRENT-PLAN.md

### Webapp Template (from YOK-671)
- Generalize bootstrap-project.sh for arbitrary projects (not just Buzz)
- Template instantiation automation script (scaffold.sh)
- Validate instantiated webapp template end-to-end (Docker, pytest, npm, auth)

### CDK Infrastructure Stack (from YOK-716)
- WAF/rate limiting on CloudFront distribution
- Monitoring/alerting for CloudFront (4xx/5xx alarm, latency)
- Multi-region or failover origin support

### Dashboard Timelines Widget (from YOK-728)
- `theme` column on `sprints` table for operator-set sprint themes
- Seasonal color variation for timeline zones
- Emoji-block rendering mode (colored squares as zone backgrounds)
- A1-A4 skyline decorative backdrop variants behind timeline

### Template Drift Detection (from YOK-760)
- Automated sync from `projects/{project}/scaffold/` to target project repo
- Pre-deploy gate that blocks deploys when template drift is detected
- Generalize `bootstrap-project.sh` beyond Buzz

### Structured Field Refactor (from YOK-762)
- Migrate FastAPI endpoints to read structured fields instead of body column
- Drop the `body` column entirely from the items table
- Structured storage for epic task descriptions
- Migrate `generate-backlog-md.sh` to use structured fields for frontmatter enrichment
- Add structured field support to the API layer

### Command Surface & Lifecycle Overhaul (from YOK-764)
- Hard-deletion of tombstone SKILL.md files (deferred to follow-up sprint)
- Pattern B auto-generated epic tasks (deferred to shepherd/architect phase)

### Dependency System (from YOK-592)
- Drop deprecated `items.depends_on` column (deferred due to trigger destruction risk with rename-copy-drop)


# Unticketed Items

- **Ouroboros product vision + goals framework** — Type: epic. `VISION.md`: Mission, Vision, Strategy, Product Vision (1/3/5 year), Business Goals, Product Goals, Technology Goals, Architecture Goals. Evaluate LBMC and other frameworks. Key requirement: every PRD links back to vision. Deliverables: (a) VISION.md, (b) PRD template `## Strategic Alignment` section, (c) prd-new SKILL.md auto-inserts alignment.
  *Note: One concrete ticket when ready: add Strategic Alignment section to PRD template.*

- **StrongDM Factory + competitive landscape research** — Type: issue. Analyze factory.strongdm.ai (every page, subpage, reference). Research BMAD, Superpowers, cursor-based factory patterns, AI-native PM tools. Produce `yoke/docs/competitive-analysis.md`. Feed into vision doc and factory mode PRD.

- **Wisdom preservation mechanism** — Type: issue. Extend `patterns.md` with `category: {operational, architectural-insight, process}` and `source: {conversation, ouroboros-log, review}`. Update `/yoke curate` for new categories. Define promotion criteria and surfacing.

- **ouroboros.dev website — PRD + design** — Type: epic. Full PRD informed by competitive analysis (item 6). Tech stack decision. Design specs from Product Designer agent. PRD + design only — implementation next sprint. First real visual design.

---

### TICKET: Test Registration and Intelligence

*Note: More sophisticated than Epic G -- this is a future capability layer. Deferred to Sprint 4+.*

**Priority:** High — core of deployment intelligence
**Type:** Epic (8-10 tasks)
**Dependencies:** Site/Environment model

**Problem:** Ouroboros has no individual test knowledge. Tests are written and run but not tracked as assets. Cannot compose intelligent test plans based on what changed and what has failed before.

**Build:**
- `tests` table: id, site (FK), name, type (unit/integration/e2e/smoke/health), command, file_path, covers (comma-separated code paths), avg_duration_ms, last_result, last_run_at, fail_count_30d, pass_count_30d, flaky (computed), created_by_item, created_by_agent, created_at
- `test_runs` table: id, test_id (FK), deployment_event_id (FK nullable), item, env_name, result (pass/fail/error/timeout/skip), duration_ms, output_summary, run_at
- `test-db.sh` domain wrapper
- `/yoke test` SKILL.md: register, list, run (single), plan (generate test plan from diff + intelligence)
- **Update tester agent contract:** after writing a test file, tester MUST register it via `yoke-db.sh` with metadata (name, type, command, file_path, covers, created_by_item). Test exists in two places: file in project repo (code) and row in Ouroboros DB (knowledge).
- Rolling stats updater: after each test_run, recompute avg_duration_ms, fail_count_30d, pass_count_30d, flaky flag
- Doctor HCs: test with no runs in 30 days (stale), test with flaky flag, site with zero registered tests

**Schema:**
```sql
CREATE TABLE tests (
  id TEXT PRIMARY KEY,
  site TEXT NOT NULL REFERENCES sites(id),
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  command TEXT NOT NULL,
  file_path TEXT,
  covers TEXT,
  avg_duration_ms INTEGER,
  last_result TEXT,
  last_run_at TEXT,
  fail_count_30d INTEGER DEFAULT 0,
  pass_count_30d INTEGER DEFAULT 0,
  flaky INTEGER DEFAULT 0,
  created_by_item TEXT,
  created_by_agent TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE test_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id TEXT NOT NULL REFERENCES tests(id),
  deployment_event_id INTEGER REFERENCES deployment_events(id),
  item TEXT,
  env_name TEXT NOT NULL,
  result TEXT NOT NULL,
  duration_ms INTEGER,
  output_summary TEXT,
  run_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

### TICKET: Test Gates and Approval Gates

*Note: Partially covered by human-approval executor. Formal gate config is a future sophistication layer. Deferred.*

**Priority:** High — controls what gets deployed and when
**Type:** Issue (medium)
**Dependencies:** Test registration

**Build:**
- `test_gates` table: site (FK), env_name, test_type, required (boolean), min_risk_level, run_order
- `approval_gates` table: site (FK), env_name, approver, approval_method (github-pr-review, dashboard, manual), min_risk_level
- Gate evaluation logic: given site + env + risk level → return required test types and approval requirements
- Doctor HCs: prod without test gates, prod without approval gate
- **Infrastructure changes require approval gates at ALL risk levels** until proven reliable

**Schema:**
```sql
CREATE TABLE test_gates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL REFERENCES sites(id),
  env_name TEXT NOT NULL,
  test_type TEXT NOT NULL,
  required INTEGER DEFAULT 1,
  min_risk_level TEXT DEFAULT 'low',
  run_order INTEGER DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE approval_gates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL REFERENCES sites(id),
  env_name TEXT NOT NULL,
  approver TEXT,
  approval_method TEXT,
  min_risk_level TEXT DEFAULT 'low',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

### TICKET: Change-Risk Classifier

*Note: Deferred. Deployment flows handle "what runs" for now.*

**Priority:** High — drives test selection and approval requirements
**Type:** Issue (medium)
**Dependencies:** Site/Environment model

**Build:**
- `classify-risk.sh`: takes changed files + project config → returns low/medium/high/critical
- Rules configurable per project in `yoke/config`
- Defaults: docs only → low, application code → medium, schema/migration changes → high, agent/hook/infrastructure files → critical, multiple subsystems → critical
- Integrate with test gate evaluation and approval gate evaluation

---

### TICKET: CDK Infrastructure Template Library

*Note: 6-month horizon. CDK is one capability type among many, not the default.*

**Priority:** Medium — enables new project provisioning
**Type:** Epic (6-8 tasks)
**Dependencies:** Project domain model, site/environment model, deploy command

**Problem:** New projects need AWS infrastructure. Currently this is manual. With CDK templates, Ouroboros can provision standard infrastructure automatically.

**Build:**
- CDK template: static site (S3 + CloudFront + Route 53 + ACM cert)
- CDK template: API service (Lambda or Fargate + API Gateway + RDS or DynamoDB)
- CDK template: full-stack (static site + API service)
- `/yoke provision` SKILL.md: select template, configure (domain, region, etc.), generate CDK stack, deploy
- `infrastructure_state` table: project, stack_name, stack_status, resources_summary, estimated_monthly_cost, last_deployed_at
- Budget alert configuration baked into every template (AWS Budgets)
- Resource limits per template (instance sizes, storage caps) as guardrails
- **All infrastructure changes require human approval** — even low-risk. CDK bugs have unbounded blast radius.
- Infrastructure Engineer agent: specialized in CDK, AWS services, cost optimization. Separate from code engineer.

---

### TICKET: Anomaly-to-Ticket Pipeline

*Note: Deferred until YOK-407 ships (needs agent_events table).*

**Priority:** Medium — closes the self-improvement loop
**Type:** Issue (medium)
**Dependencies:** Observability hooks

**Build:**
- Extend `/yoke curate` to query `agent_events` for anomaly clusters
- Auto-generate tickets for clusters above threshold (3+ occurrences of same anomaly type)
- Ticket includes: title, anomaly type, example events, frequency, affected project
- Dedup against existing open items (don't file duplicates)
- This is the automation of the current manual process: operator notices a problem, files a ticket. Now the system notices and files.

---

### TICKET: Push-Based Ouroboros Loop

*Note: Deferred until YOK-407 ships (needs system_events table).*

**Priority:** Medium — difference between "can learn" and "learns"
**Type:** Issue (medium)
**Dependencies:** Observability hooks

**Problem:** The ouroboros loop runs on human cadence — curate when you run it, wrapup when you remember. Should be event-driven.

**Build:**
- Auto-curate trigger after sprint close (conduct completes final track → fire curate)
- Auto-wrapup trigger after track completion
- Auto-check pattern promotion thresholds after curate (pattern observed N+ times → promote)
- Triggered by system events written to a `system_events` table, processed by a background loop or hook

---

### TICKET: Scenario Validation Framework

*Note: Deferred. More valuable after multi-project operation is validated.*

**Priority:** Medium — catches regressions that unit tests miss
**Type:** Epic (6-8 tasks)
**Dependencies:** None (but more valuable after project domain model)

**Build:**
- `yoke/scenarios/` directory with format spec
- `scenario-runner.sh`: sets up fresh test repo, executes scenario steps, reports pass/fail with satisfaction notes
- 5 seed scenarios: idea → shepherd → ready lifecycle, compose → sprint → tracks flow, conduct track execution end-to-end, doctor health report accuracy, "agent misinterprets ticket" failure mode detection
- Doctor HC integration: new health check runs scenarios, reports pass rate
- `/yoke scenario run [name]` command
- Future: satisfaction scoring via LLM-as-judge (probabilistic, not boolean)

---

### TICKET: Active Pattern Propagation

*Note: Deferred. Depends on scenario validation framework.*

**Priority:** Medium — factory improves factory using factory
**Type:** Epic (4-5 tasks)
**Dependencies:** Push-based ouroboros loop, scenario framework

**Problem:** Patterns are captured and promoted but require human action to apply. High-confidence patterns should generate their own improvement tickets.

**Build:**
- Add `confidence` score to patterns (0.0–1.0) computed from occurrence count, contradiction count, recency
- Add `propagation_status` field: dormant, eligible, ticket_filed, applied
- When a pattern reaches confidence threshold (e.g., 0.8) and has been promoted for N days, auto-file a ticket to modify the relevant agent prompt, SKILL.md, session rule, or build new infrastructure
- The ticket goes through the normal pipeline — shepherded, composed into a sprint, executed by the conduct
- The output type is unbounded: fix a skill, create a new skill, modify session.md, add a health check, build a completely new script

---


---
