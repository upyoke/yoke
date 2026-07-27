import { callFunction, el } from "./universe_view_support.js";
import { button } from "./workflow_view_primitives.js";

function joinNames(names) {
  if (names.length < 2) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

export function itemIntakeField(
  documentNode,
  label,
  control,
  help = null,
) {
  const wrap = el(documentNode, "label", "item-form-field");
  wrap.appendChild(el(documentNode, "span", "item-form-label", label));
  wrap.appendChild(control);
  if (help) wrap.appendChild(help);
  return wrap;
}

export function itemPostureToggle(
  documentNode,
  icon,
  title,
  copy,
  state,
  key,
  rerender,
  settingControl = null,
  enabled = true,
) {
  const row = el(documentNode, "div", "item-setting-row");
  row.appendChild(el(documentNode, "span", "item-setting-icon", icon));
  const text = el(documentNode, "div", "item-setting-copy");
  text.appendChild(el(documentNode, "strong", null, title));
  text.appendChild(el(documentNode, "span", null, copy));
  row.appendChild(text);
  if (settingControl) row.appendChild(settingControl);
  const control = button(
    documentNode,
    state[key] ? "Turn off" : "Turn on",
    `item-button${state[key] ? " primary" : ""}`,
  );
  control.disabled = !enabled;
  if (!enabled) control.title = "No verification choices are available";
  control.setAttribute("aria-pressed", String(Boolean(state[key])));
  control.addEventListener("click", () => {
    if (control.disabled) return;
    state[key] = !state[key];
    rerender();
  });
  row.appendChild(control);
  return row;
}

export function webWorkflowSteer(workflows) {
  const web = workflows.filter(
    (workflow) => (workflow.definition?.entry_surfaces || [])
      .includes("web_form"),
  );
  const harness = workflows.filter((workflow) => !web.includes(workflow));
  const webNames = web.map((workflow) => workflow.name || workflow.id);
  const harnessNames = harness.map((workflow) => workflow.name || workflow.id);
  const prefix = webNames.length === 1
    ? `Only ${webNames[0]} can currently be filed from the web.`
    : `${joinNames(webNames)} can be filed from the web.`;
  const harnessVerb = harnessNames.length === 1 ? "is" : "are";
  return {
    web,
    copy: `${prefix} ${joinNames(harnessNames)} ${harnessVerb} filed in a harness (/yoke idea).`,
  };
}

export function verificationChoiceSelect(documentNode, catalog, state) {
  const select = el(documentNode, "select", "item-setting-select");
  const choices = [
    ...catalog.plans.map((plan) => ({
      value: `plan:${plan.id}`,
      label: `plan · ${plan.slug}`,
    })),
    ...catalog.methods.map((method) => ({
      value: `method:${method.id}`,
      label: `ad hoc · ${method.name || method.id}`,
    })),
  ];
  if (!choices.length) {
    const option = el(
      documentNode,
      "option",
      null,
      "No plans or ad hoc methods available",
    );
    select.appendChild(option);
    select.disabled = true;
    return select;
  }
  if (!choices.some((choice) => choice.value === state.verification_target)) {
    state.verification_target = choices[0].value;
  }
  for (const choice of choices) {
    const option = el(documentNode, "option", null, choice.label);
    option.value = choice.value;
    option.selected = choice.value === state.verification_target;
    select.appendChild(option);
  }
  select.value = state.verification_target;
  select.addEventListener("change", () => {
    state.verification_target = select.value;
  });
  return select;
}

export async function loadVerificationCatalog(client, project) {
  const payload = { project: String(project?.slug || project?.id || "") };
  const [plans, methods] = await Promise.all([
    callFunction(client, "qa.plan.list", payload),
    callFunction(client, "qa.method.list", payload),
  ]);
  const failed = [plans, methods].find(
    (result) => !(result.status === 200 && result.envelope.success),
  ) || null;
  return {
    failed,
    plans: plans.status === 200 && plans.envelope.success
      ? plans.envelope.result?.rows || [] : [],
    methods: methods.status === 200 && methods.envelope.success
      ? methods.envelope.result?.rows || [] : [],
  };
}
