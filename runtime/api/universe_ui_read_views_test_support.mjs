import {
  byClass,
} from "./universe_ui_dom_test_support.mjs";

export function twoProjectClient() {
  const requests = [];
  const itemRow = (id, title, project) => ({
    id, title, workflow_id: "issue", workflow_version_id: 1, status: "idea", priority: "medium",
    blocked: "0", blocked_reason: "", project,
  });
  const rowsByProject = {
    1: [itemRow(11, "alpha item", "alpha")],
    2: [itemRow(21, "beta item", "beta")],
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
              rows: [
                { id: 1, slug: "alpha", name: "Alpha" },
                { id: 2, slug: "beta", name: "Beta" },
              ],
            },
          },
        };
      }
      if (request.function === "items.list.run") {
        const bucket = request.payload.project;
        const rows = bucket === undefined
          ? [...rowsByProject[1], ...rowsByProject[2]]
          : rowsByProject[bucket] || [];
        return { status: 200, envelope: { success: true, result: { rows } } };
      }
      if (request.function === "strategy.surface.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              docs: [{
                slug: `PLAN-${request.target.project_id}`,
                title: "plan",
                parent_slug: null,
                updated_at: "today",
                updated_by: "ben",
                revisions: 1,
                execution_state: "available",
                archived: false,
              }],
              writes: [],
            },
          },
        };
      }
      if (request.function === "events.query.run") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}
export function scopeChips(root) {
  return byClass(root, "scope-chip");
}

export function itemsCalls(client) {
  return client.requests.filter(
    (request) => request.function === "items.list.run",
  );
}
