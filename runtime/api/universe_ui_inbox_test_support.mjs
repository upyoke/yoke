import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

export const ok = (result) => ({
  status: 200, envelope: { success: true, result },
});

export function requestRow(overrides = {}) {
  return {
    id: 7,
    kind: "lifecycle_transition_approval",
    subject_type: "item_transition",
    subject_key: "1907:reviewing-implementation",
    // Every fixture below carries the facts its gate actually writes, as
    // `decision_request_subject_context` validates them. A fixture that
    // invents a friendlier shape lets the renderer pass its tests while the
    // served Inbox draws a row describing nothing.
    subject_context: {
      item_id: 1907,
      item_ref: "YOK-1907",
      item_title: "Approve the reviewing-implementation transition",
      from_stage: "implementing",
      to_stage: "reviewing-implementation",
      workflow_id: "dash",
      workflow_version_id: 3,
      branch_changes: {
        branch: "YOK-1907",
        commit_sha: "4bb9ea549531c896",
        touched_files: ["runtime/api/inbox.py", "docs/inbox.md"],
        summary: "+412 −87 across 9 files",
      },
      approval_source: {
        kind: "workflow_approval_default",
        entry: "approval_defaults.reviewing-implementation",
      },
      policy_summary: "dash@3 · approval_defaults.reviewing-implementation",
      title: "YOK-1907 — approve the reviewing-implementation transition",
    },
    project_id: 10,
    created_at: "2026-07-26T12:00:00Z",
    asked_of_you: false,
    authority_reason: "project owner",
    actions: ["approve", "reject"],
    ...overrides,
  };
}

export function qaRequestRow(overrides = {}) {
  return requestRow({
    id: 11,
    kind: "qa_needs_review",
    subject_type: "qa_requirement",
    subject_key: "21583",
    actions: ["waive", "reject", "approve"],
    subject_context: {
      requirement_id: 21583,
      run_id: 4120,
      plan_id: 7,
      qa_kind: "ac_verification",
      plan_name: "release-readiness",
      case_name: "marketing-pages-visual",
      method_name: "Browser inspection",
      title: "QA evidence needs your review",
      expected_outcome: "Every marketing page renders at 680px and 1024px.",
      verdict_reason:
        "Nav collapses at 680px but the spec does not state a breakpoint.",
      artifacts: [
        { artifact_id: 1, artifact_type: "screenshot", content_type: "image/png" },
        { artifact_id: 2, artifact_type: "screenshot", content_type: "image/png" },
        { artifact_id: 3, artifact_type: "log", content_type: "text/plain" },
      ],
      artifact_count: 3,
      evidence_state: "attached",
      evidence_summary: "3 attached artifact(s): log, screenshot",
    },
    ...overrides,
  });
}

// The same gate with nothing behind it. Approving this would be a verdict on
// nothing, which is the case the row has to say out loud.
export function qaBareRequestRow(overrides = {}) {
  const row = qaRequestRow(overrides);
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      artifacts: [],
      artifact_count: 0,
      evidence_state: "missing",
      evidence_summary: "No evidence artifacts are attached to this run.",
    },
  };
}

export function deploymentRequestRow(overrides = {}) {
  return requestRow({
    id: 12,
    kind: "deployment_stage_approval",
    subject_type: "deployment_stage",
    subject_key: "run-20260721-014:prod-deploy",
    subject_context: {
      run_id: "run-20260721-014",
      flow: { id: "yoke-hosted-production", name: "yoke-hosted-production" },
      stage: "prod-deploy",
      batch: {
        item_count: 2,
        items: [
          { item_id: 2712, item_ref: "YOK-2712", title: "Served context window" },
          { item_id: 2707, item_ref: "YOK-2707", title: "Messages address actors" },
        ],
      },
      shipping: {
        release_lineage: "0.1.1+launch.379",
        target_environment: "prod",
        summary: "2 item(s) ship to prod under release lineage 0.1.1+launch.379.",
      },
      title: "Deploy to prod — approve the stage",
    },
    ...overrides,
  });
}

export function machineRequestRow(overrides = {}) {
  return requestRow({
    id: 13,
    kind: "machine_approval",
    subject_type: "machine_auth_request",
    subject_key: "5b234860-c927-46ab-b19a-9fb36df056aa",
    project_id: null,
    org_id: 1,
    originator_actor_label: "dana",
    authority_reason: "org admin",
    actions: ["deny", "approve"],
    subject_context: {
      code: "WXYZ-1234",
      machine: "studio-mini",
      expires_at: "2026-09-04T12:10:00Z",
    },
    ...overrides,
  });
}

export function messageRow(overrides = {}) {
  return {
    message_id: "msg-19",
    body: "Stage deploy is red on the release gate.",
    created_at: "2026-07-26T13:00:00Z",
    project_id: 10,
    actor_receipt: { state: "pending" },
    ...overrides,
  };
}

export function inboxClient(needsRows = null) {
  const requests = [];
  let needs = needsRows ? [...needsRows] : [requestRow()];
  let messages = [messageRow()];
  return {
    requests,
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: structuredClone(needs),
          messages: structuredClone(messages),
          pending_actor_message_count: messages.length,
        });
      }
      if (request.function === "decision_requests.resolve") {
        needs = needs.filter((row) => row.id !== request.payload.request_id);
        return ok({ request: { id: request.payload.request_id, status: "resolved" } });
      }
      if (request.function === "session_control.message.acknowledge") {
        messages = messages.filter(
          (row) => row.message_id !== request.payload.message_id,
        );
        return ok({ acknowledged: true, message_id: request.payload.message_id });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export function renderInbox(scope = "all", needsRows = null) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = inboxClient(needsRows);
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [{ id: 10, slug: "yoke", name: "Yoke" }],
  }, main, scope);
  return { client, main };
}
