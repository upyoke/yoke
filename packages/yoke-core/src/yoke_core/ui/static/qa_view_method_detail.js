import { el } from "./universe_view_support.js";
import {
  capabilityLabel,
  capabilityRoute,
  capabilityStateNode,
  detailHead,
  executorContractNode,
  keyValuePanel,
  oneProjectCall,
  outcomeNode,
  projectCalls,
  qaRoute,
  relativeTimeNode,
  showFailure,
  sourceNode,
  terminalContractRows,
} from "./qa_view_primitives.js";

const RELATED_PLAN_STATE_ORDER = new Map([
  ["needs_review", 0],
  ["passed", 1],
  ["running", 2],
  ["waiting", 3],
  ["queued", 4],
  ["failed", 5],
  ["blocked_on_precondition", 6],
  ["not_run", 7],
]);

function scopeParam(scope) {
  if (scope === "all" || scope === null) return null;
  return Array.isArray(scope) ? scope.join(",") : String(scope);
}

function capabilityContract(context, method, project) {
  const documentNode = context.document;
  if (!method.required_capability_kind) {
    return el(
      documentNode, "span", "qa-no-capability",
      "none — a checkout is enough",
    );
  }
  const node = el(documentNode, "span", "qa-capability-contract");
  const link = el(
    documentNode,
    "a",
    "qa-capability-link",
    `${capabilityLabel(method.required_capability_kind)} →`,
  );
  link.href = capabilityRoute(
    context, project, method.required_capability_kind,
  );
  node.appendChild(link);
  const state = capabilityStateNode(
    documentNode,
    method.capability_context,
    method.capability_state,
  );
  if (state) node.appendChild(state);
  return node;
}

function methodContractRows(context, method, project) {
  const rows = [
    ["Executor", executorContractNode(
      context.document, method.executor_id, method.id,
    )],
    ["Capability", capabilityContract(context, method, project)],
    ["Verdict", `${method.verdict_path} — ${method.verdict_contract}`],
    ["Evidence", method.evidence_contract],
    [
      "Concurrency",
      method.concurrency_mode === "serial"
        ? "serial · one lease"
        : method.concurrency_mode,
    ],
    ["Source", sourceNode(context, method, project)],
  ];
  if (["terminal-check", "terminal-inspection"].includes(method.id)) {
    rows.push(...terminalContractRows(context.document));
  }
  return rows;
}

function planSummary(plan) {
  return plan.outcome_summary || {
    state: plan.last_outcome || "not_run",
    counts: {},
    last_at: plan.last_at || null,
  };
}

function planOutcomeLabel(plan, summary) {
  const counts = summary.counts || {};
  if (
    summary.state === "running"
    && Number(counts.running || 0) === 0
    && Number(counts.queued || 0) > 0
    && Number(counts.passed || 0) + Number(counts.waived || 0) > 0
  ) return "in progress";
  if (
    summary.state === "passed"
    && plan.method_is_complete_plan === false
    && Object.keys(counts).length === 1
    && Number(counts.passed || 0) > 1
  ) return `${counts.passed} passed`;
  return null;
}

function appendCaseSummary(documentNode, node, summary) {
  node.appendChild(el(
    documentNode, "span", "qa-plan-case-key", summary.case_key,
  ));
  for (const baseline of summary.host_baselines || []) {
    node.appendChild(el(documentNode, "span", null, " "));
    node.appendChild(el(
      documentNode, "span", "qa-host-baseline", `@${baseline}`,
    ));
  }
}

function planCaseSummaryNode(documentNode, plan, method) {
  const node = el(documentNode, "small", "qa-plan-case-summary");
  const summaries = Array.isArray(plan.case_summaries)
    ? plan.case_summaries
    : (plan.case_keys || []).map((caseKey) => ({
      case_key: caseKey,
      host_baselines: [],
    }));
  const machineCases = method.required_capability_kind === "test-machine";
  if (machineCases) {
    node.appendChild(el(
      documentNode,
      "span",
      "qa-plan-case-count",
      `${summaries.length} cases · `,
    ));
  }
  const visible = machineCases ? summaries.slice(0, 3) : summaries;
  for (const [index, summary] of visible.entries()) {
    if (index > 0) {
      node.appendChild(el(
        documentNode, "span", "qa-plan-case-separator", " · ",
      ));
    }
    appendCaseSummary(documentNode, node, summary);
  }
  if (visible.length < summaries.length) {
    node.appendChild(el(
      documentNode, "span", "qa-plan-case-separator", " · …",
    ));
  }
  return node;
}

function planResultAge(documentNode, value) {
  const age = relativeTimeNode(documentNode, value);
  const elapsed = Date.now() - new Date(value).getTime();
  if (
    Number.isFinite(elapsed)
    && elapsed >= 24 * 60 * 60 * 1000
    && elapsed < 48 * 60 * 60 * 1000
  ) {
    age.textContent = "yesterday";
  } else if (age.textContent !== "now") {
    age.textContent = `${age.textContent} ago`;
  }
  return age;
}

function planLink(context, plan, method) {
  const documentNode = context.document;
  const summary = planSummary(plan);
  const displayLabel = planOutcomeLabel(plan, summary);
  const link = el(documentNode, "a", "qa-plan-link");
  link.href = qaRoute(context, "plans", String(plan.id), plan.project);
  const copy = el(documentNode, "span");
  copy.appendChild(el(documentNode, "strong", null, plan.slug));
  copy.appendChild(planCaseSummaryNode(documentNode, plan, method));
  link.appendChild(copy);
  const outcome = el(documentNode, "span", "qa-plan-outcome");
  outcome.appendChild(outcomeNode(
    documentNode, summary.state || "not_run", null, displayLabel,
  ));
  if (summary.last_at && summary.state === "passed" && !displayLabel) {
    outcome.appendChild(planResultAge(documentNode, summary.last_at));
  }
  link.appendChild(outcome);
  return link;
}

function methodDetailSubtitle(method) {
  let source = "Project-local method";
  if (method.source_kind === "built_in") source = "Built-in method";
  if (method.source_kind === "pack") {
    source = method.source_ref
      ? `Pack-registered method · ${method.source_ref}`
      : "Pack-registered method";
  }
  return source;
}

function renderMethodDetail(context, host, method, scope) {
  const documentNode = context.document;
  const content = el(documentNode, "div", "qa-detail-grid");
  const project = scopeParam(scope);
  content.appendChild(keyValuePanel(
    documentNode,
    "Contract",
    methodContractRows(context, method, project),
  ));
  const used = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Used by plans"));
  const body = el(documentNode, "div", "panel-body qa-plan-links");
  if (!method.plans?.length) {
    body.appendChild(el(documentNode, "p", "empty", "not used by a plan yet"));
  }
  for (const plan of method.plans || []) {
    body.appendChild(planLink(context, plan, method));
  }
  used.appendChild(header);
  used.appendChild(body);
  content.appendChild(used);
  host.replaceChildren(
    detailHead(
      documentNode,
      method.name,
      methodDetailSubtitle(method),
    ),
    content,
  );
}

async function methodDetails(context, scope, methodId) {
  const calls = projectCalls(
    context, scope, "qa.method.get", { method_id: methodId },
  );
  const responses = await Promise.all(calls.map(async (call) => {
    const project = call.payload.project;
    const payload = { ...call.payload };
    delete payload.project;
    return oneProjectCall(
      context, call.functionId, project, payload,
    );
  }));
  const details = responses
    .filter((result) => result.status === 200 && result.envelope.success)
    .map((result) => result.envelope.result.method);
  return { details, failure: responses.find(
    (result) => !result.envelope?.success,
  ) };
}

function combinedPlans(details) {
  const plans = new Map();
  for (const detail of details) {
    for (const plan of detail.plans || []) {
      const identity = plan.id === null || plan.id === undefined
        ? `${plan.project || ""}:${plan.slug || ""}`
        : String(plan.id);
      if (!plans.has(identity)) plans.set(identity, plan);
    }
  }
  const combined = [...plans.values()];
  if (combined.some((plan) => !plan.outcome_summary)) return combined;
  return combined.sort((left, right) => {
    const leftSummary = planSummary(left);
    const rightSummary = planSummary(right);
    const stateOrder = (
      (RELATED_PLAN_STATE_ORDER.get(leftSummary.state) ?? 99)
      - (RELATED_PLAN_STATE_ORDER.get(rightSummary.state) ?? 99)
    );
    if (stateOrder !== 0) return stateOrder;
    const relationOrder = Number(
      right.method_is_complete_plan === true,
    ) - Number(left.method_is_complete_plan === true);
    if (relationOrder !== 0) return relationOrder;
    const leftTime = new Date(leftSummary.last_at || 0).getTime() || 0;
    const rightTime = new Date(rightSummary.last_at || 0).getTime() || 0;
    if (leftTime !== rightTime) return rightTime - leftTime;
    return String(left.project || "").localeCompare(
      String(right.project || ""),
    ) || String(left.slug || "").localeCompare(
      String(right.slug || ""),
    ) || String(left.id || "").localeCompare(String(right.id || ""));
  });
}

export async function renderQaMethodDetail(
  context, main, scope, methodId, navigation = {},
) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", `loading ${methodId}…`,
  ));
  const { details, failure } = await methodDetails(
    context, scope, methodId,
  );
  if (!context.isMounted()) return;
  if (!details.length) {
    showFailure(documentNode, main, failure || {
      envelope: { error: { message: "QA method not found." } },
    });
    return;
  }
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(details[0].name || methodId);
  }
  const plans = combinedPlans(details);
  const states = new Set(details.map((detail) => detail.capability_state));
  const capabilityState = states.size === 1 ? [...states][0] : "mixed";
  renderMethodDetail(context, main, {
    ...details[0],
    plans,
    capability_state: capabilityState,
    capability_context: details.length === 1
      ? details[0].capability_context
      : { state: capabilityState },
  }, scope);
}
