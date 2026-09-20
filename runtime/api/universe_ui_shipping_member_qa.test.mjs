// The Shipping run card used to fetch QA evidence for CARRIED_ITEMS_SHOWN
// (three) members and paint the rest as bare titles. Production
// run-20260920-005 carries twenty members and the three that rendered QA
// were exactly the first three in member_items order.

import assert from "node:assert/strict";
import test from "node:test";

import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { member } from "./universe_ui_carried_item_test_support.mjs";
import { loadDelivery } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shipping_runs.js";
import { CARRIED_ITEMS_SHOWN } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import { QA_KIND } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_state.js";

const RUN_ID = "run-20260920-005";

const MEMBERS = [
  [3444, "YOK-3281"], [3445, "YOK-3282"], [3447, "YOK-3284"],
  [3448, "YOK-3285"], [3449, "YOK-3286"], [3450, "YOK-3287"],
  [3451, "YOK-3288"], [3452, "YOK-3289"], [3453, "YOK-3290"],
  [3454, "YOK-3291"], [3457, "YOK-3294"], [3458, "YOK-3295"],
  [3460, "YOK-3297"], [3455, "YOK-3292"], [3456, "YOK-3293"],
  [3462, "YOK-3299"], [3463, "YOK-3300"], [3464, "YOK-3301"],
  [3465, "YOK-3302"], [3466, "YOK-3303"],
].map(([id, ref]) => member(id, ref));

function activityFor(itemId, overrides = {}) {
  return {
    requirement_id: 28000 + itemId,
    run_id: 29000 + itemId,
    deployment_run_id: RUN_ID,
    deployment_stage: "item-qa",
    item_id: null,
    deployment_member_item_id: itemId,
    qa_kind: "plan_case",
    qa_phase: "post_deploy",
    plan: "post-deploy",
    project: "yoke",
    case_key: `case-${itemId}`,
    method_id: "command",
    method_name: "Command",
    outcome: "passed",
    artifacts: [],
    evidence_count: 0,
    happened_at: "2026-09-20T16:00:00Z",
    ...overrides,
  };
}

function shippingClient(rows, options = {}) {
  const roster = options.members || MEMBERS;
  const runId = options.runId || RUN_ID;
  const requests = [];
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
                id: runId,
                project: "yoke",
                status: "succeeded",
                flow: "yoke-hosted-production-release-qa",
                target_environment: "prod",
                created_at: "2026-09-20T05:49:22Z",
                member_items: roster,
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
        const wanted = new Set((request.payload.item_ids || []).map(Number));
        const selected = wanted.size
          ? rows.filter((row) => wanted.has(Number(
            row.item_id ?? row.deployment_member_item_id,
          )))
          : rows.filter((row) => row.deployment_run_id === RUN_ID);
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: selected, item_selection: null, summary: { total: selected.length, counts: {} } },
          },
        };
      }
      if (request.function === "inbox.list") {
        return {
          status: 200,
          envelope: { success: true, result: { needs_decision: [] } },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

function shippingContext(documentNode, client) {
  return {
    document: documentNode,
    capabilities: {},
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    steeringGroupColors: () => new Map(),
  };
}

test("Shipping reads QA for every carried member, not the first three", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const rows = MEMBERS.map((item) => activityFor(item.id));
  const client = shippingClient(rows);
  await loadDelivery(shippingContext(documentNode, client), host, () => ["1"]);
  await settle();

  const itemReads = client.requests.filter((request) => (
    request.function === "qa.activity.list" && request.payload.item_ids
  ));
  assert.ok(itemReads.length, "the card must ask for the carried items");
  const asked = new Set(itemReads.flatMap((request) => request.payload.item_ids));
  assert.equal(asked.size, 20);
  for (const item of MEMBERS) {
    assert.ok(asked.has(item.id), `missing ${item.ref}`);
  }
});

test("run-20260920-005 shape distinguishes verified, waived, no-obligation, never-asked", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const rows = [
    activityFor(3444),
    activityFor(3445),
    activityFor(3447),
    activityFor(3448),
    {
      ...activityFor(3449, {
        requirement_id: 28801,
        case_key: "admitted-requirement-28759",
      }),
    },
    activityFor(3449, {
      requirement_id: 28759,
      run_id: null,
      deployment_run_id: null,
      item_id: 3449,
      deployment_member_item_id: null,
      case_key: "plan-currency-readable",
      outcome: "queued",
      artifacts: [],
    }),
    activityFor(3457, {
      requirement_id: 28927,
      run_id: null,
      deployment_run_id: null,
      item_id: 3457,
      deployment_member_item_id: null,
      qa_kind: QA_KIND.NOT_REQUIRED,
      method_id: null,
      outcome: "waived",
      waived_at: "2026-09-20T16:14:21Z",
      waiver_rationale: "declining it on cost",
    }),
    activityFor(3460, {
      requirement_id: 28921,
      run_id: null,
      deployment_run_id: null,
      item_id: 3460,
      deployment_member_item_id: null,
      qa_kind: QA_KIND.NO_OBLIGATION,
      method_id: null,
      outcome: "queued",
      instructions: "Nothing about this item is observable on a deployed control plane.",
    }),
    activityFor(3466, {
      outcome: "waived",
      waived_at: "2026-09-20T16:20:00Z",
      waiver_rationale: "operator authorized",
    }),
  ];
  const client = shippingClient(rows);
  await loadDelivery(shippingContext(documentNode, client), host, () => ["1"]);
  await settle();

  const members = byClass(host, "release-member");
  assert.equal(members.length, 20);
  const byRef = Object.fromEntries(MEMBERS.map((item, index) => {
    const caption = byClass(members[index], "carried-item-evidence-caption")[0];
    return [item.ref, caption ? caption.textContent : ""];
  }));
  assert.match(byRef["YOK-3281"], /verified this release/);
  assert.match(byRef["YOK-3294"], /waived/);
  assert.match(byRef["YOK-3297"], /no obligation/);
  assert.match(byRef["YOK-3290"], /never asked/);
  assert.notEqual(byRef["YOK-3294"], byRef["YOK-3297"]);
  assert.notEqual(byRef["YOK-3297"], byRef["YOK-3290"]);
});

function ancestorHidden(node) {
  for (let current = node; current; current = current.parentNode) {
    if (current.hidden) return true;
  }
  return false;
}

function membersWithQa(host, visibleOnly) {
  return byClass(host, "release-member").filter((node) => {
    if (visibleOnly && ancestorHidden(node)) return false;
    return byClass(node, "carried-item-evidence-caption").length > 0;
  });
}

test("collapsed and expanded shipping cards agree on how many members carry QA", async () => {
  const runId = "run-collapse-eight";
  const roster = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => member(4100 + n, `MEM-${n}`));
  const rows = roster.map((item) => activityFor(item.id, { deployment_run_id: runId }));
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  await loadDelivery(
    shippingContext(documentNode, shippingClient(rows, { members: roster, runId })),
    host,
    () => ["1"],
  );
  await settle();

  assert.equal(byClass(host, "release-member").length, roster.length);
  const collapsedAll = membersWithQa(host, false).length;
  const collapsedVisible = membersWithQa(host, true).length;
  assert.equal(collapsedVisible, CARRIED_ITEMS_SHOWN);
  assert.equal(collapsedAll, roster.length);

  const more = byClass(host, "release-member-more")[0];
  assert.ok(more, "the card must offer expand when it hides members");
  more.dispatchEvent(new Event("click"));

  assert.equal(membersWithQa(host, false).length, collapsedAll);
  assert.equal(membersWithQa(host, true).length, roster.length);
});
