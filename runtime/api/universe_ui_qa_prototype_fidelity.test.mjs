import assert from "node:assert/strict";
import test from "node:test";

import { renderQaMethodDetail } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_methods.js";
import { renderEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_evidence.js";
import {
  capabilityStateNode,
  outcomeNode,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_primitives.js";
import {
  reviewExplanation,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_review_explanation.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  methods,
} from "./universe_ui_qa_prototype_fidelity_data_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

async function methodDetail(method) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("main");
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        assert.equal(request.function, "qa.method.get");
        assert.equal(request.payload.method_id, method.id);
        return ok({ method });
      },
    },
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    isMounted: () => true,
  };
  await renderQaMethodDetail(context, host, ["1"], method.id);
  return {
    host,
    text: allNodes(host).map((node) => node.textContent).join(" "),
  };
}

test("all six method details retain the prototype contract anatomy", async () => {
  const expectedGloss = {
    command: "runs the case's command in the item worktree",
    "browser-check":
      "the machine-local browser daemon — recorded on every run today",
    "browser-inspection":
      "the machine-local browser daemon — recorded on every run today",
    "terminal-check": "SSH + PTY on the capability-named machine",
    "terminal-inspection": "SSH + PTY on the capability-named machine",
    "machine-state-check": "shell assertions on the controlled host",
  };

  for (const method of methods) {
    const { host, text } = await methodDetail(method);
    assert.match(text, new RegExp(expectedGloss[method.id].replace("+", "\\+")));
    assert.equal(
      byClass(host, "qa-runner-contract")[0].children[1].textContent,
      `· ${expectedGloss[method.id]}`,
    );
    for (const label of [
      "Runner", "Capability", "Verdict", "Evidence", "Concurrency", "Source",
    ]) {
      assert.match(text, new RegExp(label));
    }
    assert.match(text, /Used by plans/);
    assert.match(text, /not used by a plan yet/);
    const subtitle = byClass(host, "subtitle")[0].textContent;
    if (method.source_kind === "built_in") {
      assert.equal(subtitle, "Built-in method");
    } else {
      assert.equal(subtitle, "Pack-registered method · machine-qa");
      assert.match(text, /serial · one lease/);
      assert.match(
        byClass(host, "pill").find((node) => node.textContent === "in use").title,
        /YOK-2001/,
      );
    }
    if (method.id.startsWith("terminal-")) {
      assert.equal(allNodes(host).filter((node) => node.tagName === "EM").length, 2);
      assert.match(
        text,
        /observability follows process ancestry.*run that starts deeper/,
      );
      assert.match(
        text,
        /checkpoint not reached.*checkpoint failed.*fabricated verdict/,
      );
    }
  }
});

test("case-state explanations preserve queued, waiting, and review semantics", () => {
  const documentNode = new FakeDocument();
  const review = outcomeNode(documentNode, "needs_review");
  const queued = outcomeNode(documentNode, "queued");
  const waiting = outcomeNode(documentNode, "waiting");
  const capability = capabilityStateNode(
    documentNode,
    {
      state: "in_use",
      wait_reason: "serial_lease_in_use",
      active_lease: { item_ref: "YOK-2001" },
    },
    null,
    true,
  );

  assert.match(review.children[0].title, /does not yet have a conclusive verdict/i);
  assert.match(review.children[0].title, /runner records/);
  assert.doesNotMatch(review.children[0].title, /human decision was requested/i);
  assert.match(queued.children[0].title, /has not started/);
  assert.match(waiting.children[0].title, /required capability or serial lease/);
  assert.match(capability.title, /in use by YOK-2001/);
  assert.match(capability.title, /this case queues/);
  assert.match(capability.title, /nothing about the plan is blocked/);
});

test("review explanations derive human work only from recorded request state", () => {
  assert.match(
    reviewExplanation({ state: "awaiting_agent_review" }),
    /Agent inspection is pending; no human decision has been requested/,
  );
  assert.match(
    reviewExplanation({
      state: "agent_reviewed",
      agent_verdict: "pass",
      rationale: "The frame matches.",
    }),
    /recorded pass.*The frame matches/,
  );
  assert.doesNotMatch(
    reviewExplanation({
      state: "agent_inconclusive",
      rationale: "The evidence is ambiguous.",
    }),
    /pending in Inbox/,
  );
  assert.match(
    reviewExplanation({
      state: "human_review_requested",
      rationale: "The evidence is ambiguous.",
      decision_request: { id: 44 },
    }),
    /request 44 is pending in Inbox/,
  );
});

test("every evidence disposition renders an honest terminal state", async () => {
  const documentNode = new FakeDocument();
  const results = {
    1: {
      disposition: "ready",
      content_type: "image/png",
      content_base64: "aW1hZ2U=",
    },
    2: {
      disposition: "ready",
      content_type: "text/plain",
      content_base64: "",
    },
    3: {
      disposition: "ready",
      content_type: "application/zip",
      download_url: "https://evidence.example/object",
    },
    4: {
      disposition: "evidence_on_machine",
      machine: "Test Mac",
      detail: "the evidence bytes are not present on this machine",
    },
    5: {
      disposition: "evidence_not_portable",
      detail: "the recorded object belongs to a different artifact store",
    },
    6: {
      disposition: "too_large",
      detail: "local evidence exceeds the inline limit",
    },
  };
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        const artifactId = request.payload.artifact_id;
        if (artifactId === 7) {
          return {
            status: 503,
            envelope: {
              success: false,
              error: { message: "the artifact store is not configured" },
            },
          };
        }
        return ok({ artifact_id: artifactId, ...results[artifactId] });
      },
    },
  };
  const host = documentNode.createElement("div");
  host.appendChild(renderEvidence(context, {
    cases: [{
      case_key: "proof",
      last_result: {
        requirement_id: 41,
        evidence: Array.from({ length: 7 }, (_value, index) => ({
          id: index + 1,
          artifact_type: index === 0 ? "screenshot" : "output",
          content_type: index === 0 ? "image/png" : "text/plain",
          artifact_handle: JSON.stringify({
            backend: "local",
            path: `artifact-${index + 1}.txt`,
          }),
        })),
      },
    }],
  }));

  const actions = byClass(host, "qa-evidence-action");
  for (const action of actions) {
    action.dispatchEvent(new Event("click"));
    await settle();
  }

  assert.equal(byClass(host, "qa-evidence-preview").length, 1);
  assert.deepEqual(
    byClass(host, "qa-evidence-link").map((node) => node.textContent),
    ["open →", "view →"],
  );
  assert.deepEqual(
    actions.map((node) => node.textContent),
    ["", "", "", "on Test Mac", "not portable", "too large", "retry →"],
  );
  const text = allNodes(host).map((node) => node.textContent).join(" ");
  assert.match(text, /bytes are not present/);
  assert.match(text, /different artifact store/);
  assert.match(text, /exceeds the inline limit/);
  assert.match(text, /artifact store is not configured/);
});
