// Shared roster-read stub for the Sessions view suites: the card anatomy
// suite and the view-shell suite mount the same screen against it.
import { allNodes } from "./universe_ui_dom_test_support.mjs";

export function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

export function visibleText(root) {
  return allNodes(root).map((node) => node.textContent || "").join(" ");
}

export function sessionsClient(rows, requests, mutation = null) {
  return {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return ok({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return ok({
          rows: [{ id: 1, slug: "yoke", name: "Yoke", emoji: "🛠" }],
        });
      }
      if (request.function === "sessions.list") {
        return ok({ rows: typeof rows === "function" ? rows() : rows });
      }
      if (request.function === "sessions.reclaim_stale" && mutation) {
        return mutation(request);
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}
