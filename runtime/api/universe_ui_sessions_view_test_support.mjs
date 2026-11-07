// Shared roster-read stub for the Sessions view suites: the card anatomy
// suite and the view-shell suite mount the same screen against it.
import { allNodes, byClass } from "./universe_ui_dom_test_support.mjs";

export function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

export function visibleText(root) {
  return allNodes(root).map((node) => node.textContent || "").join(" ");
}

export function sessionsClient(
  rows, requests, mutation = null, usageRows = [],
) {
  return {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return ok({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return ok({
          rows: [{
            id: 1, slug: "yoke", name: "Yoke", emoji: "🛠",
            public_item_prefix: "YOK",
          }],
        });
      }
      if (request.function === "session_control.relay.list") {
        return ok({ relays: [] });
      }
      if (request.function === "sessions.list") {
        // The machines panel's own durable 24h-usage read, independent of
        // the roster rows this fixture otherwise serves.
        if (request.payload.usage_last_24h) return ok({ rows: usageRows });
        return ok({ rows: typeof rows === "function" ? rows() : rows });
      }
      if (request.function === "sessions.reclaim_stale" && mutation) {
        return mutation(request);
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export function setStatuses(root, values) {
  const checks = byClass(root, "session-status-filter").map((label) => label.children[1]);
  for (const check of checks) check.checked = values.includes(check.value);
  checks[0].dispatchEvent(new Event("change"));
}

export function statusChecks(root) {
  return byClass(root, "session-status-filter").map((label) => label.children[1]);
}
