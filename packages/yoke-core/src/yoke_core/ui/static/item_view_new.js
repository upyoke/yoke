import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  renderError,
} from "./universe_view_support.js";
import {
  button,
  sortedWorkflows,
  workflowPanel,
} from "./workflow_view_primitives.js";

function joinNames(names) {
  if (names.length < 2) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

function field(documentNode, label, control) {
  const wrap = el(documentNode, "label", "item-form-field");
  wrap.appendChild(el(documentNode, "span", "item-form-label", label));
  wrap.appendChild(control);
  return wrap;
}

function toggleRow(
  documentNode,
  icon,
  title,
  copy,
  state,
  key,
  rerender,
  settingControl = null,
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
  control.addEventListener("click", () => {
    state[key] = !state[key];
    rerender();
  });
  row.appendChild(control);
  return row;
}

function workflowSteer(workflows) {
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

function verificationSelect(documentNode, catalog, state) {
  const select = el(
    documentNode,
    "select",
    "item-setting-select",
  );
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

async function loadCatalog(client, project) {
  const payload = { project: String(project?.slug || project?.id || "") };
  const [plans, methods] = await Promise.all([
    callFunction(client, "qa.plan.list", payload),
    callFunction(client, "qa.method.list", payload),
  ]);
  return {
    plans: plans.status === 200 && plans.envelope.success
      ? plans.envelope.result?.rows || [] : [],
    methods: methods.status === 200 && methods.envelope.success
      ? methods.envelope.result?.rows || [] : [],
  };
}

export function renderNewItemView(context, main, projectId) {
  const documentNode = context.document;
  const project = context.projects().find(
    (row) => String(row.id) === String(projectId),
  );
  const loading = workflowPanel(documentNode, "New item");
  loading.body.textContent = "loading…";
  main.replaceChildren(loading.panel);

  Promise.all([
    callFunction(
      context.client,
      "workflows.definition.get",
      project ? { project: String(project.id) } : {},
    ),
    loadCatalog(context.client, project),
  ]).then(([callResult, catalog]) => {
    if (!context.isMounted()) return;
    if (callResult.status !== 200 || !callResult.envelope.success) {
      loading.body.replaceChildren();
      renderError(loading.body, callResult);
      return;
    }
    const workflows = sortedWorkflows(
      callResult.envelope.result?.workflows || [],
    );
    const steer = workflowSteer(workflows);
    const selected = steer.web[0];
    if (!selected) {
      loading.body.textContent =
        "No current workflow version allows the web form entry surface.";
      return;
    }
    const state = {
      verification: false,
      path_claims: false,
      approval_on_done: false,
      deployment: false,
      verification_target: "",
    };
    const title = el(documentNode, "input", "item-form-control");
    title.type = "text";
    title.maxLength = 100;
    title.required = true;
    const instruction = el(documentNode, "textarea", "item-form-control");
    instruction.required = true;
    instruction.rows = 5;
    const render = () => {
      const host = el(documentNode, "div", "item-new");
      const head = el(documentNode, "div", "item-new-heading");
      const copy = el(documentNode, "div");
      copy.appendChild(el(
        documentNode,
        "h1",
        null,
        `New ${selected.name || selected.id}`,
      ));
      copy.appendChild(el(documentNode, "p", null, steer.copy));
      head.appendChild(copy);
      const cancel = el(documentNode, "a", "item-button", "Cancel");
      cancel.href = buildUniverseRoute("items", String(projectId));
      head.appendChild(cancel);
      host.appendChild(head);

      const form = el(documentNode, "form", "item-form");
      form.appendChild(field(documentNode, "Title", title));
      form.appendChild(field(documentNode, "Instruction", instruction));
      form.appendChild(el(
        documentNode,
        "p",
        "item-form-help",
        `This is the whole spec. If the work turns out bigger than it looks, ` +
        `the agent stops, records findings, files an Issue, and cancels this ` +
        `${selected.name || selected.id} with a link.`,
      ));
      const projectField = el(documentNode, "div", "item-form-field");
      projectField.appendChild(el(
        documentNode, "span", "item-form-label", "Project",
      ));
      projectField.appendChild(el(
        documentNode,
        "strong",
        null,
        project?.name || project?.slug || String(projectId),
      ));
      form.appendChild(projectField);

      const settings = workflowPanel(documentNode, "Settings");
      const allow = new Set(
        selected.definition?.policies?.item_posture_allowlist || [],
      );
      const rows = [
        [
          "verification", "✓", "Verification",
          state.verification
            ? "choose a plan or ad hoc case — runs at reviewing-implementation"
            : "when off, we rely on agent self-check at reviewing-implementation",
        ],
        [
          "path_claims", "⛉", "Path claims",
          `reserves the files this ${selected.name || selected.id} touches, ` +
          "so overlapping work serializes instead of colliding at merge",
        ],
        [
          "approval_on_done", "☑", "Approval on done",
          "someone has to approve before it can finish — a project owner, " +
          "or a named person",
        ],
        [
          "deployment", "⬈", "Deploy after merge",
          "once the work merges, ship it through the project's delivery flow",
        ],
      ];
      for (const [key, icon, label, note] of rows) {
        if (!allow.has(key) && !(key === "approval_on_done" && allow.has("approval"))) {
          continue;
        }
        settings.body.appendChild(toggleRow(
          documentNode,
          icon,
          label,
          note,
          state,
          key,
          render,
          key === "verification" && state.verification
            ? verificationSelect(documentNode, catalog, state)
            : null,
        ));
      }
      form.appendChild(settings.panel);
      const footer = el(documentNode, "div", "item-form-actions");
      const submit = button(
        documentNode,
        `Create ${selected.name || selected.id}`,
        "item-button primary",
      );
      submit.type = "submit";
      footer.appendChild(submit);
      form.appendChild(footer);
      const outcome = el(documentNode, "p", "item-form-outcome");
      form.appendChild(outcome);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const cleanTitle = title.value.trim();
        const cleanInstruction = instruction.value.trim();
        if (!cleanTitle || !cleanInstruction) {
          outcome.className = "item-form-outcome error";
          outcome.textContent = "Title and instruction are required.";
          return;
        }
        const posture = {};
        if (state.verification) {
          const [kind, id] = state.verification_target.split(":", 2);
          posture.verification = kind === "plan"
            ? { kind: "plan", plan_id: Number(id) }
            : { kind: "ad_hoc", method_id: id };
        }
        for (const key of ["path_claims", "deployment"]) {
          if (state[key]) posture[key] = true;
        }
        if (state.approval_on_done) {
          posture[allow.has("approval_on_done")
            ? "approval_on_done" : "approval"] = true;
        }
        submit.disabled = true;
        outcome.className = "item-form-outcome";
        outcome.textContent = "Creating…";
        const result = await callFunction(context.client, "items.create", {
          title: cleanTitle,
          instruction: cleanInstruction,
          project: String(project?.slug || project?.id || projectId),
          workflow: selected.id,
          entry_surface: "web_form",
          workflow_posture: posture,
        });
        if (result.status === 200 && result.envelope.success) {
          const itemRef = result.envelope.result?.item_ref;
          outcome.textContent = `Created ${itemRef}.`;
          if (context.navigate) {
            context.navigate(buildUniverseRoute(
              "items", String(projectId), itemRef,
            ));
          }
          return;
        }
        submit.disabled = false;
        outcome.className = "item-form-outcome error";
        outcome.textContent =
          result.envelope?.error?.message || "Item creation failed.";
      });
      host.appendChild(form);
      main.replaceChildren(host);
    };
    render();
  });
}
