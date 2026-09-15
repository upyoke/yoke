// Fixtures shared by the carried-item evidence cases: the deployment-card
// surfaces and the Inbox release approval draw the same block from the same
// reads, so they describe their world once here rather than twice.

import { byClass, FakeDocument } from "./universe_ui_dom_test_support.mjs";
import { qaRequestRow } from "./universe_ui_inbox_test_support.mjs";
import { overviewRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import { loadCarriedItemEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";

export const RUN_ID = "run-20260910-009";
const PNG = "iVBORw0KGgo=";

export function artifact(id, requirementId) {
  return {
    id,
    artifact_type: "screenshot",
    content_type: "image/png",
    requirement_id: requirementId,
    metadata: { label: `shot-${id}`, step_index: id },
  };
}

export function activityRow(overrides = {}) {
  return {
    requirement_id: 26134,
    run_id: 28095,
    deployment_run_id: null,
    deployment_stage: null,
    item_id: 1896,
    deployment_member_item_id: null,
    plan_id: 7,
    plan: "release-readiness",
    project: "yoke",
    case_key: "marketing-pages-visual",
    method_name: "Browser inspection",
    outcome: "undetermined",
    artifacts: [artifact(17882, 26134), artifact(17883, 26134)],
    evidence_count: 2,
    happened_at: "2026-09-10T09:00:00Z",
    ...overrides,
  };
}

export function runRow(items) {
  return {
    id: RUN_ID,
    project: "yoke",
    status: "failed",
    flow: "yoke-hosted-stage-consumer-bound",
    target_environment: "stage",
    created_at: "2026-09-10T10:00:00Z",
    stages: [{ name: "release", state: "failed" }],
    gates: [],
    member_items: items,
  };
}

export function member(id, ref, overrides = {}) {
  return {
    id,
    ref,
    title: `${ref} title`,
    project_id: 1,
    project_sequence: id,
    ...overrides,
  };
}

// A client that answers the two reads the carried-item evidence needs, and
// records every request so a case can assert what was actually asked for.
export function readingClient({ rows = [], pending = [], resolves = [], selection = null } = {}) {
  const requests = [];
  return {
    requests,
    resolves,
    async call(request) {
      requests.push(request);
      if (request.function === "qa.activity.list") {
        const wanted = new Set((request.payload.item_ids || []).map(Number));
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: rows.filter((row) => wanted.has(
                Number(row.item_id ?? row.deployment_member_item_id),
              )),
              item_selection: selection,
              summary: { day: "2026-09-10", total: rows.length, counts: {} },
            },
          },
        };
      }
      if (request.function === "inbox.list") {
        return {
          status: 200,
          envelope: { success: true, result: { needs_decision: pending } },
        };
      }
      if (request.function === "decision_requests.resolve") {
        resolves.push(request.payload);
        return { status: 200, envelope: { success: true, result: {} } };
      }
      if (request.function === "qa.artifact.read") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              disposition: "ready",
              content_type: "image/png",
              content_base64: PNG,
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export function readingContext(documentNode, client) {
  return {
    document: documentNode,
    capabilities: {},
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };
}

export async function cardFor(documentNode, items, client, onItemDecision = null) {
  const context = readingContext(documentNode, client);
  const itemFacts = await loadCarriedItemEvidence(context, items);
  return {
    itemFacts,
    card: overviewRunCard(context, runRow(items), ["1"], {
      facts: { evidence: new Map(), flowNames: new Map(), failed: null },
      itemFacts,
      onItemDecision,
    }),
  };
}

export function memberEntry(card, index = 0) {
  return byClass(card, "overview-run-member")[index];
}

// A review names the item it is about, so bounding an item's older checks
// must never take its live request off the page with them.
export function itemReviewRow(overrides = {}) {
  const base = qaRequestRow();
  return qaRequestRow({
    status: "pending",
    subject_context: {
      ...base.subject_context,
      requirement_id: 99999,
      subject: {
        ...base.subject_context.subject,
        kind: "item",
        item_id: 1896,
        item_ref: "BUZ-1896",
        deployment_run_id: null,
      },
    },
    ...overrides,
  });
}
