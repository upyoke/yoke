import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  capabilityRoute,
  sourceNode,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_primitives.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import { mountAt } from "./universe_ui_qa_view_test_support.mjs";

test("Pack sources and Test Mac capability relations keep their prototype routes", () => {
  const documentNode = new FakeDocument();
  const primitiveContext = {
    document: documentNode,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };
  const source = sourceNode(primitiveContext, {
    source_kind: "pack",
    source_ref: "machine-qa",
  }, "yoke");
  const cardSource = sourceNode(primitiveContext, {
    source_kind: "pack",
    source_ref: "machine-qa",
  }, "yoke", false);

  assert.equal(byClass(source, "qa-source-link")[0].href, "#/packs?project=1");
  assert.equal(byClass(cardSource, "qa-source-link").length, 0);
  assert.equal(cardSource.textContent, "Pack");
  assert.equal(
    capabilityRoute(primitiveContext, "yoke", "test-machine"),
    "#/capabilities/test-machine?project=1",
  );
});

test("QA defaults to the prototype Methods roster and opens contract detail", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa?project=1",
  );

  assert.deepEqual(
    byClass(root, "tab-link").map((node) => node.textContent),
    ["Methods", "Plans", "Activity"],
  );
  assert.equal(byClass(root, "qa-method-card").length, 2);
  assert.deepEqual(
    byClass(root, "qa-method-card").map(
      (node) => byClass(node, "qa-method-identity")[0].children[0].textContent,
    ),
    ["Command", "Browser check"],
  );
  for (const card of byClass(root, "qa-method-card")) {
    assert.equal(
      byClass(card, "qa-source")[0].parentNode,
      byClass(card, "qa-method-top")[0],
    );
  }
  const text = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(
    text,
    /Test plans prove the work; methods say how; capabilities make it possible/,
  );
  assert.match(text, /requires nothing — a checkout is enough/);
  assert.match(text, /requires\s+Browser control\s+·\s+ready/);
  assert.doesNotMatch(text, /How methods enter this project/);
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.method.list"),
    { function: "qa.method.list", payload: { project: "1" } },
  );

  const methodLink = byClass(root, "qa-method-card")[0];
  assert.equal(methodLink.tagName, "A");
  assert.equal(methodLink.href, "#/qa/methods/command?project=1");
  root.ownerDocument.defaultView.location.hash = methodLink.href;
  root.ownerDocument.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  const detailText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.equal(byClass(root, "breadcrumb").length, 1);
  assert.deepEqual(
    byClass(root, "breadcrumb")[0].children.map((node) => node.textContent),
    ["QA", "›", "Methods", "›", "Command"],
  );
  assert.equal(byClass(root, "page-head").length, 1);
  assert.equal(byClass(root, "tab-bar").length, 0);
  assert.equal(byClass(root, "qa-detail-page-head").length, 1);
  assert.match(detailText, /Contract/);
  assert.match(
    detailText,
    /worktree_run · runs the case's command in the item worktree/,
  );
  assert.match(detailText, /Used by plans/);
  assert.match(detailText, /release-readiness/);
  assert.match(detailText, /passed/);
  mounted.unmount();
});

test("Plans renders the durable objects and the full case-detail composition", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa/plans?project=1",
  );

  assert.equal(byClass(root, "qa-plans-table").length, 1);
  const listText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(listText, /release-readiness/);
  assert.match(listText, /project default · review/);
  assert.doesNotMatch(listText, /project default · Review gate/);
  assert.match(listText, /item · YOK-2001/);
  assert.doesNotMatch(listText, /item · YOK-2001 · reviewing-implementation/);
  assert.match(listText, /1 needs review/);
  assert.equal(
    byClass(root, "qa-method-summary")[0].children
      .map((node) => node.textContent)
      .join(""),
    "2·⌥◎",
  );
  assert.equal(byClass(root, "qa-result-age").length, 0);
  assert.equal(byClass(root, "qa-relative-time").length, 0);
  assert.match(
    listText,
    /yoke qa plan create --project yoke release-readiness/,
  );

  const planLink = byClass(root, "qa-plan-button")[0];
  assert.equal(planLink.tagName, "A");
  assert.equal(planLink.href, "#/qa/plans/7?project=1");
  root.ownerDocument.defaultView.location.hash = planLink.href;
  root.ownerDocument.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  const detailText = allNodes(root).map((node) => node.textContent).join(" ");
  assert.equal(byClass(root, "breadcrumb").length, 1);
  assert.deepEqual(
    byClass(root, "breadcrumb")[0].children.map((node) => node.textContent),
    ["QA", "›", "Plans", "›", "release-readiness"],
  );
  assert.equal(byClass(root, "page-head").length, 1);
  assert.match(
    detailText,
    /gates the reviewed-implementation transition/,
  );
  assert.match(detailText, /issue · reviewing-implementation/);
  assert.doesNotMatch(detailText, /Review gate|Implementation review/);
  assert.match(
    detailText,
    /Rerun and waive are per-case engine actions on the materialized requirement, authority-checked at resolve\./,
  );
  assert.equal(byClass(root, "tab-bar").length, 0);
  assert.equal(byClass(root, "qa-detail-page-head").length, 1);
  assert.match(detailText, /Case sequence/);
  assert.match(detailText, /backend-suite/);
  assert.match(detailText, /checkout-flow/);
  assert.match(detailText, /cold-start-hosted/);
  assert.match(detailText, /@fresh-host/);
  assert.match(detailText, /@shell-preconfigured/);
  assert.match(detailText, /all 5 case-baseline proofs pass/);
  assert.match(detailText, /union: gate not satisfied/);
  assert.match(detailText, /Attached to/);
  assert.match(detailText, /Evidence by case/);
  assert.match(detailText, /output.txt/);
  assert.equal(byClass(root, "qa-case-actions")[2].textContent, "—");
  assert.match(
    detailText,
    /yoke qa plan edit release-readiness/,
  );
  const evidenceAction = byClass(root, "qa-evidence-action")[0];
  assert.equal(evidenceAction.tagName, "BUTTON");
  assert.equal(evidenceAction.textContent, "view →");
  evidenceAction.dispatchEvent(new Event("click"));
  await settle();
  assert.match(
    allNodes(root).map((node) => node.textContent).join(" "),
    /open →/,
  );
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.artifact.read"),
    {
      function: "qa.artifact.read",
      payload: { artifact_id: 4 },
      target: { kind: "qa_requirement", qa_requirement_id: 31 },
    },
  );
  byClass(root, "qa-evidence-action")[1].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.filter(
      (request) => request.function === "qa.artifact.read",
    ).at(-1),
    {
      function: "qa.artifact.read",
      payload: { artifact_id: 6 },
      target: { kind: "qa_requirement", qa_requirement_id: 34 },
    },
  );

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Rerun",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.case.rerun"),
    {
      function: "qa.case.rerun",
      payload: {},
      target: { kind: "qa_requirement", qa_requirement_id: 31 },
    },
  );

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Waive",
  ).dispatchEvent(new Event("click"));
  const rationale = byClass(root, "qa-waiver-rationale")[0];
  rationale.value = "Equivalent external proof was reviewed.";
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Waive case",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find((request) => request.function === "qa.case.waive"),
    {
      function: "qa.case.waive",
      payload: { rationale: "Equivalent external proof was reviewed." },
      target: { kind: "qa_requirement", qa_requirement_id: 32 },
    },
  );
  assert.equal(byClass(root, "qa-action-overlay").length, 0);

  const freshRow = allNodes(root).find((node) =>
    node.tagName === "TR"
    && allNodes(node).some((child) => child.textContent === " @fresh-host")
  );
  allNodes(freshRow).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Rerun",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.filter(
      (request) => request.function === "qa.case.rerun",
    ).at(-1),
    {
      function: "qa.case.rerun",
      payload: {},
      target: { kind: "qa_requirement", qa_requirement_id: 34 },
    },
  );

  const shellRow = allNodes(root).find((node) =>
    node.tagName === "TR"
    && allNodes(node).some(
      (child) => child.textContent === " @shell-preconfigured",
    )
  );
  allNodes(shellRow).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Waive",
  ).dispatchEvent(new Event("click"));
  assert.match(
    allNodes(byClass(root, "qa-action-dialog")[0])
      .map((node) => node.textContent).join(" "),
    /cold-start-hosted @shell-preconfigured/,
  );
  byClass(root, "qa-waiver-rationale")[0].value =
    "The shell baseline has equivalent proof.";
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Waive case",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.filter(
      (request) => request.function === "qa.case.waive",
    ).at(-1),
    {
      function: "qa.case.waive",
      payload: { rationale: "The shell baseline has equivalent proof." },
      target: { kind: "qa_requirement", qa_requirement_id: 35 },
    },
  );
  mounted.unmount();
});
