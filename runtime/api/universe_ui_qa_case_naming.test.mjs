// A QA case goes by one name everywhere — what ran, against what — and that
// name is the link to its case page. Rows do not navigate as a whole, and a
// command check's case page shows the output it recorded.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  qaCaseName,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_case_name.js";
import {
  renderQaActivity,
  renderQaCaseDetail,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_qa.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const CI_RUN = "https://github.com/upyoke/platform/actions/runs/1234";
const OUTPUT = "12 passed in 3.4s\n";

const RUN_CHECK = {
  requirement_id: 32037, run_id: 70, deployment_run_id: "run-20260927-004",
  item_id: null, deployment_member_item_id: null, plan_id: null, plan: null,
  project: "yoke", method_id: "browser-inspection", method_name: "Browser inspection",
  outcome: "passed", evidence_count: 0, artifacts: [],
  happened_at: "2026-09-27T16:40:00Z",
};
const ITEM_CHECK = {
  requirement_id: 31877, run_id: 71, deployment_run_id: null, item_id: 3589,
  plan_id: null, plan: null, project: "yoke", method_id: "command",
  method_name: "Command", outcome: "passed", run_url: CI_RUN,
  evidence_count: 1,
  artifacts: [{ id: 22502, artifact_type: "command_output", content_type: "text/plain",
    metadata: "{\"exit_code\": 0}" }],
  happened_at: "2026-09-27T16:30:00Z",
};

function qaContext(documentNode, { rows, requirement, navigate = () => {} }) {
  const requests = [];
  return {
    requests,
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
    navigate,
    capabilities: {},
    client: {
      async call(request) {
        requests.push(request);
        switch (request.function) {
          case "qa.activity.list":
            return ok({ summary: { total: rows.length, counts: {} }, rows });
          case "inbox.list":
            return ok({ needs_decision: [], messages: [] });
          case "items.detail.get":
            return ok({ item: {
              id: 3589, public_ref: "PLAT-151", project: { id: 3, slug: "platform" },
            } });
          case "qa.requirement.get":
            return ok({ requirement });
          case "qa.run.list":
            return ok({ rows: [{ id: 71, verdict: "pass", case_outcome: "passed",
              completed_at: "2026-09-27T16:30:00Z" }] });
          case "qa.artifact.read":
            return ok({ artifact_id: request.payload.artifact_id, disposition: "ready",
              content_type: "text/plain",
              content_base64: Buffer.from(OUTPUT).toString("base64") });
          default:
            throw new Error(`unexpected function ${request.function}`);
        }
      },
    },
  };
}

test("a case is named for its method and the item or run it answers for", () => {
  assert.equal(qaCaseName(RUN_CHECK), "Browser inspection · run-20260927-004");
  assert.equal(qaCaseName(ITEM_CHECK, "PLAT-151"), "Command check · PLAT-151");
  // A release check run for a carried item answers for that item.
  assert.equal(
    qaCaseName({ ...RUN_CHECK, deployment_member_item_id: 3589 }, "PLAT-151"),
    "Browser inspection · PLAT-151",
  );
  // An unresolved ref keeps the id it has rather than dropping the subject.
  assert.equal(qaCaseName(ITEM_CHECK), "Command check · item 3589");
});

test("activity links each case by name and the row itself does not navigate", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const navigations = [];
  const context = qaContext(documentNode, {
    rows: [RUN_CHECK, ITEM_CHECK], navigate: (href) => navigations.push(href),
  });
  await renderQaActivity(context, root, "all");
  await settle();

  const links = byClass(root, "qa-activity-link");
  assert.deepEqual(
    links.map((link) => [link.textContent, link.href]),
    [
      ["Browser inspection · run-20260927-004", "#/qa-activity/32037?project=1"],
      ["Command check · PLAT-151", "#/qa-activity/31877?project=1"],
    ],
  );
  assert.equal(byClass(root, "qa-clickable-row").length, 0);
  const rows = byClass(root, "qa-activity-row");
  assert.equal(rows.length, 2);
  rows[0].dispatchEvent(new Event("click"));
  assert.deepEqual(navigations, []);
  // One item read per subject item, none for a run check.
  assert.equal(
    context.requests.filter((r) => r.function === "items.detail.get").length, 1,
  );
});

test("activity lists every case run the day's count covers, run checks included", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const today = [...Array(8)].map((_, index) => ({
    ...(index % 2 ? ITEM_CHECK : RUN_CHECK),
    requirement_id: 40000 + index,
    happened_at: `2026-09-27T1${index}:00:00Z`,
  }));
  const context = qaContext(documentNode, {
    rows: [...today, { ...RUN_CHECK, requirement_id: 39999, happened_at: "2026-09-26T09:00:00Z" }],
  });
  context.client.call = ((call) => async (request) => {
    const response = await call(request);
    if (request.function === "qa.activity.list") {
      response.envelope.result.summary = { day: "2026-09-27", total: 8, counts: {} };
    }
    return response;
  })(context.client.call.bind(context.client));
  await renderQaActivity(context, root, "all");
  await settle();

  assert.equal(byClass(root, "qa-stat")[0].children[0].textContent, "8");
  const names = byClass(root, "qa-activity-link").map((link) => link.textContent);
  assert.equal(names.length, 8);
  assert.equal(names.filter((name) => name.startsWith("Browser inspection · run-")).length, 4);
  assert.equal(
    context.requests.find((r) => r.function === "qa.activity.list").payload.limit, 500,
  );
});

test("a command check's case page shows its recorded output and CI run", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const labels = [];
  const context = qaContext(documentNode, {
    rows: [ITEM_CHECK],
    requirement: { id: 31877, item_id: 3589, method_id: "command", method_name: "Command" },
  });
  await renderQaCaseDetail(context, root, "1", "31877", {
    setDetailLabel: (label) => labels.push(label),
  });
  await settle();

  // Title and breadcrumb carry the same name the activity table links.
  assert.equal(byClass(root, "title")[0].textContent, "Command check · PLAT-151");
  assert.deepEqual(labels, ["Command check · PLAT-151"]);
  const output = byClass(root, "qa-case-recorded-output");
  assert.equal(output.length, 1);
  assert.equal(output[0].textContent, OUTPUT.trimEnd());
  assert.equal(byClass(root, "qa-case-output-label")[0].textContent, "Recorded output · exit 0");
  // The read names its case: qa.artifact.read is project-scoped, and without
  // a requirement target the server cannot resolve the project and refuses.
  const read = context.requests.find((r) => r.function === "qa.artifact.read");
  assert.deepEqual(read.target, { kind: "qa_requirement", qa_requirement_id: 31877 });
  // The output is shown as text, not repeated as an evidence tile.
  assert.equal(byClass(root, "review-shot").length, 0);
  assert.doesNotMatch(root.textContent, /could not be resolved/);
  const ci = byClass(root, "qa-case-ci-link")[0];
  assert.equal(ci.textContent, "GitHub Actions run");
  assert.equal(ci.href, CI_RUN);
  assert.equal(ci.target, "_blank");
});

test("a carried item's check is found under the item's own project", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("main");
  const context = qaContext(documentNode, {
    rows: [],
    requirement: { id: 31877, deployment_run_id: "run-20260927-004",
      deployment_member_item_id: 3589, method_id: "command" },
  });
  await renderQaCaseDetail(context, root, "1", "31877");
  await settle();

  const projects = context.requests
    .filter((r) => r.function === "qa.activity.list")
    .map((r) => r.payload.project);
  assert.deepEqual([...new Set(projects)], ["1", "platform", "3"]);
  // With no row anywhere, the page still says so rather than inventing one.
  assert.match(root.textContent, /could not be resolved from here/);
});

test("every text link is underlined; chips, pills, tabs and tiles are not", () => {
  const staticRoot = new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url,
  );
  const read = (name) => readFileSync(new URL(name, staticRoot), "utf8");
  assert.match(read("app.css"), /@import url\("\.\/universe_link_underline\.css"\)/);
  const sheet = read("universe_link_underline.css");
  const [linkRule] = sheet.match(/main\.content a\[href\][^{]*\{[^}]*\}/);
  assert.match(linkRule, /text-decoration: underline/);
  for (const excluded of [
    ".tab-link", ".review-shot-open", ".review-pill", ".nav-link",
    '[class*="chip"]', '[class*="pill"]', '[class*="card"]',
  ]) {
    assert.ok(linkRule.includes(`:not(${excluded})`), excluded);
  }
  assert.match(sheet, /details > summary:not\(\[class\]\)[\s\S]*text-decoration: underline/);
  assert.match(sheet, /summary\.disclosure-link/);
  assert.doesNotMatch(read("qa_details.css"), /qa-clickable-row/);
});
