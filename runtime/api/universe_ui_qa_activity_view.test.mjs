import assert from "node:assert/strict";
import test from "node:test";

import { renderEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_evidence.js";
import {
  renderQaActivity,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_activity.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";
import { ok } from "./universe_ui_qa_view_data_test_support.mjs";
import { mountAt } from "./universe_ui_qa_view_test_support.mjs";

test("Evidence view actions expose local and stranded dispositions honestly", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        requests.push(request);
        return ok(request.payload.artifact_id === 4
          ? {
              artifact_id: 4,
              disposition: "evidence_on_machine",
              machine: "Test Mac",
              detail: "Open this evidence from its capture machine.",
            }
          : {
              artifact_id: 5,
              disposition: "evidence_not_portable",
              detail: "The artifact handle survived, but its bytes did not.",
            });
      },
    },
  };
  const host = documentNode.createElement("div");
  host.appendChild(renderEvidence(context, {
    cases: [{
      case_key: "marketing-pages-visual",
      last_result: {
        requirement_id: 32,
        evidence: [
          {
            id: 4,
            artifact_type: "screenshot",
            content_type: "image/png",
            artifact_handle:
              "{\"backend\":\"local\",\"path\":\"footer-strip.png\"}",
          },
          {
            id: 5,
            artifact_type: "screenshot",
            content_type: "image/png",
            artifact_handle:
              "{\"backend\":\"s3\",\"key\":\"checkout-summary.png\"}",
          },
        ],
      },
    }],
  }));
  await settle();

  assert.match(
    allNodes(host).map((node) => node.textContent).join(" "),
    /Evidence · marketing-pages-visual/,
  );
  const actions = byClass(host, "qa-evidence-action");
  assert.deepEqual(
    actions.map((node) => node.textContent),
    ["on Test Mac", "not portable"],
  );
  assert.deepEqual(
    requests.map((request) => request.target),
    [
      { kind: "qa_requirement", qa_requirement_id: 32 },
      { kind: "qa_requirement", qa_requirement_id: 32 },
    ],
  );
});

test("Activity folds hidden QA plumbing into readable outcomes", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa-activity?project=1",
  );

  assert.equal(byClass(root, "qa-stat").length, 4);
  assert.deepEqual(
    byClass(root, "qa-stat").map(
      (card) => card.children.map((node) => node.textContent),
    ),
    [
      ["10", "case runs today"],
      ["8", "passed"],
      ["1", "needs review"],
      ["1", "running"],
    ],
  );
  assert.equal(byClass(root, "qa-clickable-row").length, 6);
  const columns = ["Plan", "Case", "Method", "Outcome", "Evidence", "Review", "When"];
  assert.deepEqual(
    allNodes(byClass(root, "qa-activity-table")[0])
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    columns,
  );
  // Each cell names its column, which is what lets a phone stack the row
  // rather than push Outcome, Evidence and Review off the right edge.
  assert.ok(
    byClass(root, "qa-activity-table")[0].classList.contains("table-stacks-narrow"),
  );
  assert.deepEqual(
    allNodes(byClass(root, "qa-clickable-row")[0])
      .filter((node) => node.tagName === "TD")
      .map((node) => node.attributes.get("data-label")),
    columns,
  );
  // And the row a reader taps opens that exact case, which is the only way
  // to reach its evidence once the columns are stacked.
  assert.equal(
    byClass(root, "qa-activity-link")[1].href,
    "#/qa-activity/32?project=1",
  );
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "qa.activity.list",
    ),
    {
      function: "qa.activity.list",
      payload: { project: "1", limit: 6 },
    },
  );
  const text = visibleText(root, " ");
  assert.match(text, /case runs today/);
  assert.match(text, /release-readiness/);
  assert.match(text, /checkout-flow/);
  assert.match(text, /Browser check/);
  assert.match(text, /needs review/);
  assert.match(text, /4 screenshots/);
  assert.doesNotMatch(text, /4 artifacts/);
  assert.deepEqual(
    byClass(root, "qa-outcome").map((node) => node.children[0].textContent),
    [
      "needs review",
      "running",
      "passed · capture degraded",
      "passed",
      "passed",
      "blocked on precondition",
    ],
  );
  assert.equal(byClass(root, "qa-outcome-reason").length, 0);
  assert.equal(
    text.match(/image capture blocked on the host/g)?.length,
    1,
  );
  assert.equal(
    text.match(/capability went error/g)?.length,
    1,
  );
  assert.match(
    text,
    /Blocked on precondition is neither a pass nor a case failure — the case's host baseline could not be reached or verified\./,
  );
  mounted.unmount();
});

test("Activity labels every merged row with its owning project", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const requests = [];
  const projects = [
    { id: 1, slug: "alpha", name: "Alpha" },
    { id: 2, slug: "beta", name: "Beta" },
  ];
  const context = {
    document: documentNode,
    projects: () => projects,
    isMounted: () => true,
    navigate: () => {},
    client: {
      async call(request) {
        requests.push(request);
        if (request.function === "inbox.list") {
          return ok({ needs_decision: [], messages: [] });
        }
        const project = projects.find(
          (row) => String(row.id) === String(request.payload.project),
        );
        return ok({
          summary: { total: 1, counts: { passed: 1 } },
          rows: [{
            requirement_id: project.id,
            plan_id: project.id,
            plan: `${project.slug}-plan`,
            project: project.slug,
            case_key: "browser-proof",
            method_id: "browser-check",
            method_name: "Browser check",
            outcome: "passed",
            evidence_count: 1,
            proof_summary: "1 screenshot",
            happened_at: `2026-07-2${project.id}T12:00:00Z`,
          }],
        });
      },
    },
  };

  await renderQaActivity(context, root, "all");

  assert.deepEqual(
    requests.filter((request) => request.function === "qa.activity.list")
      .map((request) => request.payload.project),
    ["1", "2"],
  );
  assert.deepEqual(
    allNodes(byClass(root, "qa-activity-table")[0])
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["Plan", "project", "Case", "Method", "Outcome", "Evidence", "Review", "When"],
  );
  assert.deepEqual(
    byClass(root, "qa-activity-project").map((node) => node.textContent),
    ["beta", "alpha"],
  );
  // The Plan cell opens the plan; the Case cell opens that case run, which
  // is what the row is about.
  assert.deepEqual(
    byClass(root, "qa-activity-link").map((node) => node.href),
    [
      "#/qa-plans/2?project=2", "#/qa-activity/2?project=2",
      "#/qa-plans/1?project=1", "#/qa-activity/1?project=1",
    ],
  );
});

test("a row's linked artifacts render as thumbnails, and a pending review points at the Inbox", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  await renderQaActivity({
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate: () => {},
    capabilities: {},
    client: {
      async call(request) {
        if (request.function === "inbox.list") {
          return ok({ needs_decision: [{
            id: 77, kind: "qa_needs_review", project_id: 1,
            subject_context: { requirement_id: 9 },
          }], messages: [] });
        }
        if (request.function === "qa.activity.list") {
          return ok({
            summary: { total: 1, counts: { passed: 1 } },
            rows: [{
              requirement_id: 9,
              plan_id: 9,
              plan: "release-readiness",
              project: "yoke",
              case_key: "browser-proof",
              method_id: "browser-check",
              method_name: "Browser check",
              outcome: "passed",
              evidence_count: 1,
              proof_summary: "1 screenshot",
              happened_at: "2026-07-29T12:00:00Z",
              artifacts: [{
                id: 7,
                artifact_type: "screenshot",
                content_type: "image/png",
                artifact_handle:
                  "{\"backend\":\"s3\",\"key\":\"proof.png\"}",
              }],
            }],
          });
        }
        return ok({ disposition: "unavailable" });
      },
    },
  }, root, "all");
  await settle();

  assert.equal(byClass(root, "review-shot").length, 1);
  assert.match(visibleText(root, " "), /proof\.png/);
  const review = byClass(root, "qa-activity-review")[0];
  assert.equal(byClass(review, "review-pill")[0].textContent, "needs your review →");
  assert.equal(byClass(review, "review-pill")[0].href, "#/inbox?project=1");
});

test("a case attached without a plan reads as such and is named by its method", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  await renderQaActivity({
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate: () => {},
    capabilities: {},
    client: {
      async call(request) {
        if (request.function === "inbox.list") {
          return ok({ needs_decision: [], messages: [] });
        }
        return ok({
          summary: { total: 1, counts: { passed: 1 } },
          // An item's own ad hoc verification: no plan, so no case key
          // either. Both read as absent rather than as a plan the table
          // failed to name.
          rows: [{
            requirement_id: 26759,
            plan_id: null,
            plan: null,
            project: "yoke",
            case_key: null,
            method_id: "browser-inspection",
            method_name: "Browser inspection",
            outcome: "passed",
            evidence_count: 0,
            proof_summary: "",
            happened_at: "2026-09-16T12:00:00Z",
          }],
        });
      },
    },
  }, root, "all");
  await settle();

  // The Plan cell says there is none, and offers no link to a plan page
  // that does not exist.
  const row = byClass(root, "qa-clickable-row")[0];
  assert.equal(row.children[0].children[0].textContent, "no plan");
  assert.equal(byClass(row, "qa-activity-link").length, 1);
  // The case is named by what executes it, and still opens its own page.
  const caseLink = byClass(row, "qa-activity-link")[0];
  assert.equal(caseLink.textContent, "Browser inspection");
  assert.equal(caseLink.href, "#/qa-activity/26759?project=1");
});
