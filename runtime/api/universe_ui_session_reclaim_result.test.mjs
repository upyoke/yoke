import assert from "node:assert/strict";
import test from "node:test";
import { renderSessionsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { ok } from "./universe_ui_sessions_view_test_support.mjs";

for (const recheck of [false, true]) {
  test(`new protection is explained when mutation recheck=${recheck}`, async () => {
    const documentNode = new FakeDocument();
    const main = documentNode.createElement("main");
    let reclaimed = false;
    const context = {
      document: documentNode,
      isMounted: () => true,
      projects: () => [],
      steeringGroupColors: () => new Map(),
      refreshSteeringGroupColors: async () => {},
      client: {
        async call(request) {
          if (request.function === "sessions.reclaim_stale") {
            reclaimed = true;
            return ok({ total_reclaimed: 0, skipped_between_turns: [{
              session_id: "new-holder", reason: "active_work_claim", recheck,
            }] });
          }
          if (request.payload.usage_last_24h) return ok({ rows: [] });
          return ok({ rows: [{
            session_id: "new-holder", executor: "codex",
            liveness: reclaimed ? "active" : "stale", reclaimable: !reclaimed,
            claims: [], messageability: { messageable: false },
          }] });
        },
      },
    };
    renderSessionsView(context, main, "all");
    await settle();
    const reclaim = allNodes(main).find((node) => node.tagName === "BUTTON"
      && node.textContent === "Reclaim stale");
    assert.equal(reclaim.disabled, false);
    reclaim.dispatchEvent(new Event("click"));
    await settle();
    const status = byClass(main, "sessions-action-status")[0].textContent;
    assert.match(status, /0 stale sessions reclaimed/);
    assert.match(status, /new-holder: active_work_claim; refresh the roster before retrying/);
    assert.equal(reclaim.disabled, true);
  });
}
