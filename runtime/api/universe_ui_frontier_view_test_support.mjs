// A frontier universe with one ready step and one blocked row per gate
// point, so both panels and every gate pill family render from one read.
export function frontierClient() {
  const requests = [];
  const blockedRow = (itemId, gatePoint, why, blocker = {}) => ({
    item_id: itemId, title: `waits ${itemId}`, project: "yoke",
    project_id: 1, project_sequence: Number(itemId.split("-").at(-1)),
    blocking_item: blocker.ref || "YOK-7",
    blocking_project_id: blocker.projectId || 1,
    blocking_project_sequence: blocker.sequence || 7,
    gate_point: gatePoint, why,
    satisfaction: "status:done", workflow_id: "issue",
    created_at: "2026-07-20T10:00:00Z",
  });
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
                { id: 1, slug: "yoke", name: "Yoke", emoji: "🐄" },
                { id: 2, slug: "platform", name: "Platform" },
              ],
            },
          },
        };
      }
      if (request.function === "frontier.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              ready_rows: [{
                rank: 0, item_id: "YOK-7", title: "ship it",
                workflow_id: "issue", workflow_version: 1,
                project: "yoke", project_id: 1, project_sequence: 7,
                status: "implementing",
                priority: "high", next_step: "advance",
                run_command: "yoke advance YOK-7",
                why_ready: "No unsatisfied activation gates; unclaimed.",
                unblocks_count: 3, downstream_depth: 1,
                stage_index: 4, stage_count: 10, stage_label: "Implement",
                created_at: "2026-07-20T10:00:00Z",
              }],
              blocked_rows: [
                blockedRow("YOK-8", "activation", "YOK-7 not done"),
                blockedRow(
                  "YOK-9", "integration", "lands after PLT-70",
                  { ref: "PLT-70", projectId: 2, sequence: 70 },
                ),
                blockedRow("YOK-10", "closure", "closes after YOK-7"),
              ],
              frozen_count: 0, wip_cap: 5, wip_active: 1,
            },
          },
        };
      }
      if (request.function === "sessions.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: request.payload.liveness === "active"
                ? [{ session_id: "session-1", owns_current_item: true }]
                : [],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}
