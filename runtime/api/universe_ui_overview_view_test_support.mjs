import { allNodes } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({
  status: 200, envelope: { success: true, result },
});
const fail = () => ({
  status: 500,
  envelope: { success: false, error: { message: "boom" } },
});
const recentIso = (hours = 1) => new Date(
  Date.now() - hours * 60 * 60 * 1000,
).toISOString();

function item(ref, project, projectId, facts = {}) {
  return {
    public_ref: ref,
    title: `${project} item`,
    project,
    project_id: projectId,
    project_sequence: Number(ref.split("-").at(-1)),
    workflow_id: "issue",
    status: "planned",
    created_at: recentIso(12),
    updated_at: recentIso(1),
    ...facts,
  };
}

function session(sessionId, project, projectId) {
  return {
    session_id: sessionId,
    liveness: "active",
    project,
    project_id: projectId,
    executor: "codex",
    model: "gpt-5.6-sol",
    execution_lane: "implementation",
    mode: "charge",
    actor_id: 2,
    actor_kind: "human",
    actor_label: "Ben",
    activity_at: recentIso(0.1),
  };
}

export function multiProjectOverviewClient({ failProject } = {}) {
  const requests = [];
  const projects = [
    { id: 1, slug: "yoke", name: "Yoke", emoji: "🐄", public_item_prefix: "YOK" },
    { id: 2, slug: "beta", name: "Beta", emoji: "🐝", public_item_prefix: "BET" },
  ];
  const items = [
    item("YOK-9", "yoke", 1),
    item("YOK-8", "yoke", 1, { frozen: true }),
    item("BET-20", "beta", 2),
    item("BET-19", "beta", 2, { status: "done", merged_at: recentIso(2) }),
  ];
  const universe = {
    "items.overview.list": { rows: items },
    "frontier.list": {
      ready_rows: [
        { ...items[0], item_id: "YOK-9", why_ready: "ready" },
        { ...items[2], item_id: "BET-20", why_ready: "ready" },
      ],
      blocked_rows: [],
    },
    "sessions.list": {
      rows: [session("s-yoke", "yoke", 1), session("s-beta", "beta", 2), {
        ...session("s-nil", null, null), project: null, project_id: null,
      }],
    },
    "overview.activation.get": { dismiss_available: false, modules: [] },
  };
  return {
    requests,
    projects,
    async call(request) {
      requests.push(request);
      const fn = request.function;
      const project = String(
        request.payload?.project ?? request.target?.project_id ?? "1",
      );
      if (fn === "organizations.get") return ok({ name: "Yoke" });
      if (fn === "projects.list") return ok({ rows: projects });
      if (fn === "strategy.doc.list") {
        if (project === failProject) return fail();
        return ok({ docs: [{
          slug: project === "2" ? "BETA-PLAN" : "MISSION",
          summary: project === "2" ? "Beta direction" : "Yoke direction",
          updated_at: recentIso(project === "2" ? 2 : 1),
          state: "available",
        }] });
      }
      if (fn === "strategy.doc_claim.list") return ok({ claims: [] });
      if (fn === "deployment_runs.list") return ok({ rows: [{
        id: project === "2" ? "run-beta" : "run-yoke",
        project: project === "2" ? "beta" : "yoke",
        target_environment: "stage",
        status: "executing",
        flow: "release",
        created_at: recentIso(project === "2" ? 2 : 1),
        stages: [],
      }] });
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

export function overviewClient(overrides = {}) {
  const requests = [];
  const frozen = item("YOK-7", "yoke", 1, {
    frozen: true,
    blocked_reason: "Waiting for a product decision.",
  });
  const ready = item("YOK-9", "yoke", 1, {
    title: "Ship typed workflows",
  });
  const done = item("YOK-6", "yoke", 1, {
    title: "Land the release",
    status: "done",
    merged_at: recentIso(2),
    deployed_to: "stage",
  });
  const answers = {
    "items.overview.list": { rows: [frozen, ready, done] },
    "frontier.list": {
      ready_rows: [{
        ...ready,
        item_id: "YOK-9",
        why_ready: "No blockers; specification and plan are current.",
        run_command: "yoke advance YOK-9",
      }],
      blocked_rows: [],
    },
    "sessions.list": { rows: [{
      ...session("s-run", "yoke", 1),
      current_item: "YOK-9",
      current_item_title: "Ship typed workflows",
      owns_current_item: true,
      claims: [],
    }] },
    "strategy.doc.list": { docs: [
      {
        slug: "MISSION", summary: "Build a calmer delivery system.",
        updated_at: recentIso(1), state: "available",
      },
      {
        slug: "DELIVERY-PLAN", summary: "Ship the next reliable slice.",
        updated_at: recentIso(48), state: "locked",
      },
      {
        slug: "OLD-PLAN", summary: "Superseded direction.",
        updated_at: recentIso(96), state: "available", archived: true,
      },
    ] },
    "strategy.doc_claim.list": { claims: [
      {
        strategy_doc_slug: "MISSION", project_id: 1,
        owner_kind: "session", holder_label: "steering seat",
      },
      {
        strategy_doc_slug: "DELIVERY-PLAN", project_id: 1,
        owner_kind: "item", public_ref: "YOK-9", item_status: "implementing",
      },
    ] },
    "deployment_runs.list": { rows: [{
      id: "run-1",
      project: "yoke",
      flow: "yoke-hosted-stage",
      target_environment: "stage",
      status: "executing",
      created_at: recentIso(1),
      release_lineage: "abcdef1234567890",
      stages: [
        { name: "build", state: "complete" },
        { name: "deploy", state: "active" },
      ],
      member_items: [{ ref: "YOK-9", title: "Ship typed workflows" }],
    }] },
    "overview.activation.get": { dismiss_available: false, modules: [] },
    ...overrides,
  };
  const projects = [{
    id: 1, slug: "yoke", name: "Yoke", emoji: "🐄",
    public_item_prefix: "YOK",
  }];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") return ok({ rows: projects });
      if (request.function in answers) return ok(answers[request.function]);
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}
