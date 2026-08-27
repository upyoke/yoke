import assert from "node:assert/strict";
import test from "node:test";

import {
  renderQaPlanDetail,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_plan_detail_view.js";
import {
  executionTargetLabel,
  renderExecutionTarget,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_execution_target_view.js";
import {
  renderEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_evidence.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function visibleText(node) {
  return allNodes(node).map((child) => child.textContent).join(" ");
}

test("project targets explain that no deployment environment is required", () => {
  const documentNode = new FakeDocument();
  const target = {
    schema: 3,
    target_kind: "project",
    tenant: { id: 1, slug: "upyoke", name: "UpYoke" },
    project: { id: 2, slug: "yoke", name: "Yoke" },
    endpoints: {},
  };

  assert.equal(
    executionTargetLabel(target),
    "project source · no deployment environment",
  );
  const text = visibleText(renderExecutionTarget(documentNode, {
    execution_target: target,
  }));
  assert.match(text, /project source · no deployment environment/);
  assert.doesNotMatch(text, /undefined|Not bound/);

  const environment = {
    schema: 2,
    tenant: { slug: "upyoke", name: "UpYoke" },
    project: { slug: "yoke", name: "Yoke" },
    environment: { name: "stage" },
    endpoints: { app_url: "https://stage.example.test" },
  };
  assert.equal(executionTargetLabel(environment), "upyoke · stage");
  assert.doesNotMatch(
    visibleText(renderExecutionTarget(documentNode, {
      execution_target: environment,
    })),
    /undefined|Not bound/,
  );
});

test("plan detail uses transition ids and carries the per-case authority copy", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const plan = {
    id: 7,
    project: "yoke",
    slug: "release-readiness",
    cases: [{
      id: 1,
      case_key: "backend-suite",
      position: 1,
      method_name: "Command",
      required_capability_kinds: [],
      required_capabilities: [],
      last_result: {
        requirement_id: 31,
        run_id: 91,
        outcome: "failed",
        output_tail: "AssertionError: checkout confirmation was absent",
        evidence: [],
      },
    }],
    attachments: [{
      kind: "project_default",
      project: "yoke",
      workflow_id: "issue",
      transition_id: "RELEASE",
      transition_label: "Mutable Release Name",
    }, {
      kind: "item",
      project: "yoke",
      workflow_id: "issue",
      transition_id: "REVIEWING-IMPLEMENTATION",
      transition_label: "Mutable Review Name",
      item_ref: "YOK-2001",
    }],
    union: { satisfied: false, counts: { failed: 1 } },
  };
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        assert.equal(request.function, "qa.plan.get");
        assert.deepEqual(request.payload, { plan_id: 7, project: "1" });
        return ok({ plan });
      },
    },
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };

  await renderQaPlanDetail(context, host, ["1"], "7");

  const text = visibleText(host);
  assert.match(text, /the release transition waits/);
  assert.match(text, /gates the release transition for every yoke item/);
  assert.match(text, /issue · reviewing-implementation/);
  assert.doesNotMatch(text, /Mutable Release Name|Mutable Review Name/);
  assert.match(
    text,
    /Waive is a per-case engine action on the materialized requirement, authority-checked at resolve\./,
  );
  assert.match(text, /failure output/);
  assert.match(text, /AssertionError: checkout confirmation was absent/);
});

test("hosted evidence makes local handles explicitly on-machine", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  const context = {
    document: documentNode,
    capabilities: { data: { portability: { mode: "hosted" } } },
    client: {
      async call(request) {
        requests.push(request);
        if (request.payload.artifact_id === 2) {
          return ok({
            artifact_id: 2,
            disposition: "evidence_not_portable",
            detail: "The durable handle points at a stranded object.",
          });
        }
        return {
          status: 404,
          envelope: {
            success: false,
            error: { message: "Artifact record missing." },
          },
        };
      },
    },
  };
  const host = documentNode.createElement("div");
  host.appendChild(renderEvidence(context, {
    cases: [{
      case_key: "marketing-pages-visual",
      last_result: {
        requirement_id: 32,
        evidence: [{
          id: 1,
          artifact_type: "screenshot",
          content_type: "image/png",
          artifact_handle:
            "{\"backend\":\"local\",\"path\":\"footer-strip.png\"}",
        }, {
          id: 2,
          artifact_type: "screenshot",
          content_type: "image/png",
          artifact_handle:
            "{\"backend\":\"s3\",\"key\":\"checkout-summary.png\"}",
        }, {
          id: 3,
          artifact_type: "screenshot",
          content_type: "image/png",
          artifact_handle:
            "{\"backend\":\"s3\",\"key\":\"missing.png\"}",
        }],
      },
    }],
  }));

  assert.equal(byClass(host, "panel-count").length, 0);
  assert.match(
    visibleText(host),
    /local handle — on this machine only; viewable where it was captured, not from this browser/,
  );
  const actions = byClass(host, "qa-evidence-action");
  assert.deepEqual(
    actions.map((node) => [node.tagName, node.textContent]),
    [["SPAN", "on-machine"], ["BUTTON", "view →"], ["BUTTON", "view →"]],
  );
  assert.equal(
    allNodes(host).some((node) =>
      node.tagName === "BUTTON" && node.textContent === "footer-strip.png"
    ),
    false,
  );

  actions[1].dispatchEvent(new Event("click"));
  await settle();
  actions[2].dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    requests.map((request) => request.payload.artifact_id),
    [2, 3],
  );
  assert.deepEqual(
    requests.map((request) => request.target),
    [
      { kind: "qa_requirement", qa_requirement_id: 32 },
      { kind: "qa_requirement", qa_requirement_id: 32 },
    ],
  );
  assert.deepEqual(
    actions.map((node) => node.textContent),
    ["on-machine", "not portable", "retry →"],
  );
  assert.match(visibleText(host), /stranded object/);
  assert.match(visibleText(host), /Artifact record missing/);
});

test("local evidence keeps the artifact read behavior", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  const context = {
    document: documentNode,
    capabilities: { data: { portability: { mode: "local" } } },
    client: {
      async call(request) {
        requests.push(request);
        return ok({
          artifact_id: 1,
          disposition: "ready",
          content_type: "image/png",
          content_base64: "aW1hZ2U=",
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
        evidence: [{
          id: 1,
          artifact_type: "screenshot",
          content_type: "image/png",
          artifact_handle:
            "{\"backend\":\"local\",\"path\":\"footer-strip.png\"}",
        }],
      },
    }],
  }));

  const action = byClass(host, "qa-evidence-action")[0];
  assert.equal(action.tagName, "BUTTON");
  assert.equal(action.textContent, "view →");
  action.dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(requests, [{
    function: "qa.artifact.read",
    payload: { artifact_id: 1 },
    target: { kind: "qa_requirement", qa_requirement_id: 32 },
  }]);
  assert.equal(byClass(host, "qa-evidence-preview").length, 1);
});
