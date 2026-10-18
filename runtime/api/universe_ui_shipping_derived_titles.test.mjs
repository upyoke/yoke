// A stage run with no recorded members still names each carried item.
// Its payload often omits the title, and it must not ask for item QA.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { DEPLOYED_SHA, member } from "./universe_ui_carried_item_test_support.mjs";
import { loadDelivery } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shipping_runs.js";

const RUN_ID = "run-20260920-005";

function derivedClient() {
  const requests = [];
  const item = member(1, "YOK-1", { title: "", project_id: null });
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "deployment_runs.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{
                id: RUN_ID,
                project: "yoke",
                status: "succeeded",
                flow: "yoke-hosted-production-release-qa",
                target_environment: "prod",
                release_lineage: DEPLOYED_SHA,
                created_at: "2026-09-20T05:49:22Z",
                member_items: [],
                carried_work: { items: [item] },
                gates: [],
              }],
            },
          },
        };
      }
      if (request.function === "sessions.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      if (request.function === "workflows.definition.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { flows: [{ id: "yoke-hosted-production-release-qa", name: "prod" }] },
          },
        };
      }
      if (request.function === "qa.activity.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: [], item_selection: null, summary: { total: 0, counts: {} } },
          },
        };
      }
      if (request.function === "inbox.list") {
        return { status: 200, envelope: { success: true, result: { needs_decision: [] } } };
      }
      if (request.function === "items.detail.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { item: { title: `${request.target.public_ref} title` } },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

test("a stage run with no recorded members shows titles and no item QA", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const client = derivedClient();
  await loadDelivery({
    document: documentNode,
    capabilities: {},
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    steeringGroupColors: () => new Map(),
  }, host, () => ["1"]);
  await settle();
  assert.equal(client.requests.filter((request) => (
    request.function === "qa.activity.list" && request.payload.public_refs
  )).length, 0);
  assert.equal(client.requests.filter((request) => (
    request.function === "items.detail.get"
  )).length, 1);
  assert.match(host.textContent, /YOK-1 title/);
  assert.doesNotMatch(host.textContent, /item_qa_requirements_unavailable/);
  assert.match(host.textContent, /No item QA owed on this target/);
});
