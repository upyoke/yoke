// An item page lists every landing it made, and a card says when there were
// several.
//
// Before this, an item that landed four times in one day read exactly like
// one that landed once: the page said "merged" from its status, and nothing
// anywhere named a second landing.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  workItemCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_work_cards.js";
import {
  FakeDocument,
  byClass,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";
import { settle } from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
} from "./universe_ui_items_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const LANDINGS = [
  {
    id: 11, item_id: 51, merge_sha: "a".repeat(40), candidate_sha: "b".repeat(40),
    pr_number: "1301", target_branch: "main", route: "merge_queue",
    landed_at: "2026-09-19T03:12:00Z",
    delivery: { run_id: "run-20260919-012", flow: "acme-prod" },
  },
  {
    id: 12, item_id: 51, merge_sha: "c".repeat(40), candidate_sha: "c".repeat(40),
    pr_number: "", target_branch: "main", route: "fast_forward",
    landed_at: "2026-09-19T18:41:00Z", delivery: null,
  },
  {
    id: 13, item_id: 51, merge_sha: "d".repeat(40), candidate_sha: "e".repeat(40),
    pr_number: "", target_branch: "main", route: "standalone",
    landed_at: "2026-09-19T23:02:00Z", delivery: null,
  },
];

function landingsClient(item, landings, { fail = false, unreadable = false } = {}) {
  return async (request) => {
    if (request.function === "items.detail.get") return ok({ item });
    if (request.function === "item_landings.list") {
      if (fail) return { status: 500, envelope: { success: false } };
      return ok({
        item_id: 51,
        rows: unreadable
          ? landings.map(({ delivery, ...rest }) => rest)
          : landings,
        count: landings.length,
        delivery_unreadable: unreadable,
      });
    }
    if (request.function === "deployment_runs.find_by_item") {
      return ok({ item_id: 51, fields: [], rows: [] });
    }
    if (request.function === "workflows.mechanics.get") {
      return ok({ delivery_defaults: [], testing_defaults: [], approvers: [] });
    }
    if (request.function === "qa.artifact.read") {
      return ok({ disposition: "unavailable" });
    }
    if (request.function === "inbox.list") return ok({ needs_decision: [] });
    if (request.function === "sessions.list") return ok({ rows: [] });
    if (request.function === "epic_tasks.list.run") return ok({ tasks: [] });
    if (request.function === "strategy.execution.get") return ok({ document: null });
    throw new Error(`unexpected function ${request.function}`);
  };
}

async function renderLandings(landings, options = {}) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderItemDetailView(
    itemContext(documentNode, landingsClient(detailItem("dash"), landings, options)),
    root, "7", "ACM-22",
  );
  await settle();
  await settle();
  return root;
}

test("a second landing reads as a second row, not as a replacement", async () => {
  const root = await renderLandings(LANDINGS);

  const rows = byClass(root, "item-landing");
  assert.equal(rows.length, 3);
  // Oldest first, so a reader follows the branch forward through its landings.
  assert.deepEqual(
    byClass(root, "item-landing-ordinal").map((node) => node.textContent),
    ["#1", "#2", "#3"],
  );
  assert.deepEqual(
    byClass(root, "item-landing-merge").map((node) => node.textContent),
    ["aaaaaaaaaaaa", "cccccccccccc", "dddddddddddd"],
  );
  // The whole sha stays reachable for an auditor settling which merge it was.
  assert.equal(byClass(root, "item-landing-merge")[0].title, "a".repeat(40));
});

test("each landing names how it landed and the pull request that carried it", async () => {
  const root = await renderLandings(LANDINGS);

  assert.deepEqual(
    byClass(root, "item-landing-route").map((node) => node.textContent),
    ["merge queue", "fast-forward", "merge"],
  );
  // Only the landing that had one: a fast-forward has no pull request, and an
  // empty chip would read as one that could not be resolved.
  assert.deepEqual(
    byClass(root, "item-landing-pr").map((node) => node.textContent),
    ["#1301"],
  );
});

test("a landing names the release that delivered it, or that none has", async () => {
  const root = await renderLandings(LANDINGS);

  const release = byClass(root, "item-landing-release");
  assert.equal(release.length, 1);
  assert.equal(release[0].textContent, "run-20260919-012");
  assert.equal(release[0].href, "#/deployments/runs/run-20260919-012?project=7");
  assert.deepEqual(
    byClass(root, "item-landing-undelivered").map((node) => node.textContent),
    ["not delivered", "not delivered"],
  );
});

test("an item that landed once shows one landing and no comparison", async () => {
  const root = await renderLandings([LANDINGS[0]]);

  assert.equal(byClass(root, "item-landing").length, 1);
  assert.equal(byClass(root, "item-landing-ordinal")[0].textContent, "#1");
});

test("an item that never landed draws no panel at all", async () => {
  const root = await renderLandings([]);

  assert.equal(byClass(root, "item-landing").length, 0);
  assert.equal(byClass(root, "item-landings-panel")[0].hidden, true);
});

test("a read that failed says so rather than reading as never landed", async () => {
  const root = await renderLandings([], { fail: true });

  assert.equal(byClass(root, "item-landings-panel")[0].hidden, false);
  assert.match(
    visibleText(root, " "), /Landings for this item could not be read\./,
  );
});

test("a card reports landing churn only when there is churn to report", () => {
  const documentNode = new FakeDocument();
  const row = {
    public_ref: "ACM-22", project_id: 7, project_sequence: 22,
    title: "lands more than once", workflow_id: "dash", status: "release",
    updated_at: "2026-09-19T23:02:00Z",
  };
  const churned = workItemCard(
    documentNode, { ...row, landing_count: 4 }, [7],
  );
  assert.deepEqual(
    byClass(churned, "work-item-card-landings").map((n) => n.textContent),
    ["4 landings"],
  );
  for (const count of [0, 1, undefined]) {
    const quiet = workItemCard(documentNode, { ...row, landing_count: count }, [7]);
    assert.equal(
      byClass(quiet, "work-item-card-landings").length, 0,
      `landing_count=${count} must add nothing to the card`,
    );
  }
});

test("a reconstructed landing names that its timestamp is approximate", async () => {
  const reconstructed = {
    ...LANDINGS[1],
    origin: "reconstructed",
  };
  const root = await renderLandings([LANDINGS[0], reconstructed]);

  assert.deepEqual(
    byClass(root, "item-landing-origin").map((node) => node.textContent),
    ["reconstructed"],
  );
  assert.equal(
    byClass(root, "item-landing-when")[1].title,
    "git committer time; minutes early of a merge-queue landing",
  );
});

test("a delivery the read could not resolve is unknown, not undelivered", async () => {
  // The landings are still the audit record; what failed is the second
  // question over release state. Reporting it as "nothing shipped this" would
  // be a false answer to a question nobody managed to ask.
  const root = await renderLandings(LANDINGS, { unreadable: true });

  assert.equal(byClass(root, "item-landing").length, 3);
  assert.equal(byClass(root, "item-landing-undelivered").length, 0);
  assert.equal(byClass(root, "item-landing-release").length, 0);
  assert.deepEqual(
    byClass(root, "item-landing-unknown").map((node) => node.textContent),
    ["delivery unknown", "delivery unknown", "delivery unknown"],
  );
});
