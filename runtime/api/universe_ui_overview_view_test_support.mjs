import { allNodes } from "./universe_ui_dom_test_support.mjs";

// A two-project universe whose per-project fan-out reads (vitals, events,
// doctor, strategy) answer by request.payload.project / request.target so a
// held "all" mount holds each project's own rows — and whose universe reads
// (frontier, sessions, delivery) carry a project on every row so a client-side
// scope narrow can partition them. Used by the held-read rescope regressions.
export function multiProjectOverviewClient() {
  const requests = [];
  const projects = [
    { id: 1, slug: "yoke", name: "Yoke", emoji: "🐄" },
    { id: 2, slug: "beta", name: "Beta", emoji: "🐝" },
  ];
  const ok = (result) => ({ status: 200, envelope: { success: true, result } });
  const vitalsFor = (project) => ({
    state_counts: project === "2"
      ? { active: 1, pipeline: 0, backlog: 0, blocked: 0, frozen: 0, done: 5 }
      : { active: 3, pipeline: 2, backlog: 4, blocked: 1, frozen: 0, done: 20 },
    momentum: [{ day: "2026-07-26", activity: 1, code: 1, issues: 0, strategy: 0 }],
    strategy_timeline: [{
      project_id: Number(project), project: project === "2" ? "beta" : "yoke",
      done_positions: [], labels: [], queued_count: 0, vision_zones: [],
    }],
    days: 120,
  });
  const docsFor = (projectId) => ({
    docs: [{
      slug: projectId === "2" ? "BETA-PLAN" : "MISSION", title: "why",
      updated_at: "today", execution_state: "available",
    }],
  });
  const eventsFor = (project) => ({
    rows: [{
      created_at: "30s", event_name: project === "2" ? "BetaEvent" : "YokeEvent",
      source_label: "sys", target_label: "t", context_label: "c",
    }],
  });
  const doctorFor = (project) => ({
    never_run: false, ran_at: "today", total: 10, pass_count: 9,
    warn_count: 1, fail_count: 0,
    results: [{
      hc: "HC-x", name: project === "2" ? "beta-check" : "yoke-check",
      severity: "warn",
    }],
  });
  const universe = {
    "frontier.list": {
      ready_rows: [
        {
          item_id: "YOK-9", title: "Yoke item", project: "yoke", rank: 0,
          workflow_id: "issue", run_command: "yoke advance YOK-9",
          why_ready: "ok", created_at: "2026-07-26T11:00:00Z",
        },
        {
          item_id: "YOK-20", title: "Beta item", project: "beta", rank: 1,
          workflow_id: "issue", run_command: "yoke advance YOK-20",
          why_ready: "ok", created_at: "2026-07-25T11:00:00Z",
        },
      ],
      blocked_rows: [],
    },
    "sessions.list": {
      rows: [
        {
          session_id: "s-yoke", liveness: "active", project: "yoke",
          executor: "codex", model: "m", execution_lane: "L", mode: "charge",
          actor_id: 2, actor_kind: "human", activity_at: "2026-07-26T12:00:00Z",
        },
        {
          session_id: "s-beta", liveness: "active", project: "beta",
          executor: "codex", model: "m", execution_lane: "L", mode: "charge",
          actor_id: 2, actor_kind: "human", activity_at: "2026-07-26T12:00:00Z",
        },
        {
          session_id: "s-nil", liveness: "active", project: null,
          executor: "codex", model: "m", execution_lane: "L", mode: "charge",
          actor_id: 2, actor_kind: "human", activity_at: "2026-07-26T12:00:00Z",
        },
      ],
    },
    "deployment_runs.list": {
      rows: [
        {
          id: "run-yoke", project: "yoke", target_env: "stage",
          status: "succeeded", created_at: "1h", stages: [],
        },
        {
          id: "run-beta", project: "beta", target_env: "stage",
          status: "succeeded", created_at: "2h", stages: [],
        },
      ],
    },
    "overview.activation.get": { dismiss_available: false, modules: [] },
  };
  return {
    requests,
    projects,
    async call(request) {
      requests.push(request);
      const fn = request.function;
      if (fn === "organizations.get") return ok({ name: "Yoke" });
      if (fn === "projects.list") return ok({ rows: projects });
      if (fn === "overview.vitals.get") {
        return ok(vitalsFor(String(request.payload.project ?? "1")));
      }
      if (fn === "events.query.run") {
        return ok(eventsFor(String(request.payload.project)));
      }
      if (fn === "doctor.last_run.get") {
        return ok(doctorFor(String(request.payload.project)));
      }
      if (fn === "strategy.doc.list") {
        return ok(docsFor(String((request.target || {}).project_id)));
      }
      if (fn in universe) return ok(universe[fn]);
      throw new Error(`unexpected function ${fn}`);
    },
  };
}

export function descendantText(root) {
  return allNodes(root)
    .filter((node) => node.children.length === 0)
    .map((node) => node.textContent || "")
    .join("");
}

// A one-project universe that answers every read the Overview composes. Rows
// are shaped like the engine's, so the summary panels render the same columns
// their full screens do.
export function overviewClient(overrides = {}) {
  const requests = [];
  const answers = {
    "frontier.list": {
      ready_rows: [
        {
          item_id: "YOK-9", title: "Ship typed workflows",
          workflow_id: "issue", workflow_version_id: 1, project: "yoke",
          status: "planned", priority: "high", rank: 0,
          stage_index: 2, stage_count: 5, stage_label: "planned",
          next_step: "advance", run_command: "yoke advance YOK-9",
          why_ready: "No blockers · specification and plan are current",
          created_at: "2026-07-26T11:00:00Z",
        },
        {
          item_id: "YOK-8", title: "Finish session presence",
          workflow_id: "issue", workflow_version_id: 1, project: "yoke",
          status: "refined-idea", priority: "medium", rank: 1,
          stage_index: 1, stage_count: 5, stage_label: "refined",
          next_step: "conduct", run_command: "yoke conduct YOK-8",
          why_ready: "Claims are free · capacity is available",
          created_at: "2026-07-25T11:00:00Z",
        },
      ],
      blocked_rows: [
        {
          item_id: "YOK-7", title: "Approval surface",
          workflow_id: "issue", project: "yoke", blocking_item: "YOK-9",
          gate_point: "activation", why: "waits for YOK-9",
          created_at: "2026-07-20T11:00:00Z",
        },
      ],
    },
    "sessions.list": {
      rows: [
        {
          session_id: "s-run", liveness: "active", execution_lane: "primary",
          mode: "charge", actor_id: 2, actor_kind: "human", actor_label: "Ben",
          project: "yoke", executor: "codex", model: "gpt-5.6-sol",
          claims: [], current_item: "YOK-9",
          current_item_title: "Ship typed workflows",
          owns_current_item: true, activity_at: "2026-07-26T11:30:00Z",
        },
      ],
    },
    "strategy.doc.list": {
      docs: [{
        slug: "MISSION", title: "why", updated_by: "ben",
        updated_at: "today", bytes: 10, archived: false,
      }],
    },
    "deployment_runs.list": {
      rows: [{
        id: "run-1", project: "yoke",
        flow: "yoke-hosted-stage", target_env: "stage",
        current_stage: "complete", status: "succeeded", created_at: "1h",
        waiting_on_approval: false,
        stages: [
          { name: "build", state: "complete" },
          { name: "deploy", state: "complete" },
        ],
      }],
    },
    "events.query.run": {
      rows: [{
        created_at: "30s", event_name: "YokeFunctionCalled",
        event_kind: "function", severity: "info", actor_id: "codex",
        source_label: "codex · desktop",
        target_label: "items.structured_field.replace",
        context_label: "YOK-9",
      }],
    },
    "doctor.last_run.get": {
      never_run: false, ran_at: "today", total: 44, pass_count: 42,
      warn_count: 2, fail_count: 0,
      results: [
        { hc: "HC-title-length", name: "titles", severity: "pass" },
        { hc: "HC-stale-migration", name: "migrations", severity: "warn" },
      ],
    },
    "overview.activation.get": { dismiss_available: false, modules: [] },
    "overview.vitals.get": {
      state_counts: {
        active: 3, pipeline: 2, backlog: 4, blocked: 1, frozen: 0, done: 2828,
      },
      momentum: [
        { day: "2026-07-25", activity: 2, code: 1, issues: 1, strategy: 0 },
        { day: "2026-07-26", activity: 4, code: 2, issues: 0, strategy: 1 },
      ],
      strategy_timeline: [{
        project_id: 1,
        project: "yoke",
        emoji: "🐄",
        done_positions: [8, 42, 88],
        labels: [
          { position: 8, label: "registry" },
          { position: 42, label: "items" },
        ],
        queued_count: 3,
        vision_zones: [
          { key: "1mo", label: "web steering" },
          { key: "6mo", label: "multi-actor" },
        ],
      }],
      days: 120,
    },
    ...overrides,
  };
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{ id: 1, slug: "yoke", name: "Yoke", emoji: "🐄" }],
            },
          },
        };
      }
      if (request.function in answers) {
        return { status: 200, envelope: { success: true, result: answers[request.function] } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}
