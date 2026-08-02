import { buildUniverseRoute } from "./universe_navigation.js";
import {
  itemIntakeField,
  itemPostureToggle,
  loadVerificationCatalog,
  verificationChoiceSelect,
  webWorkflowSteer,
} from "./item_intake_controls.js";
import { callFunction, el, renderError } from "./universe_view_support.js";
import {
  button, sortedWorkflows, workflowPanel,
} from "./workflow_view_primitives.js";

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
    loadVerificationCatalog(context.client, project),
  ]).then(([callResult, catalog]) => {
    if (!context.isMounted()) return;
    if (callResult.status !== 200 || !callResult.envelope.success) {
      loading.body.replaceChildren();
      renderError(loading.body, callResult);
      return;
    }
    if (catalog.failed) {
      loading.body.replaceChildren();
      renderError(loading.body, catalog.failed);
      return;
    }
    const workflows = sortedWorkflows(
      callResult.envelope.result?.workflows || [],
    );
    const steer = webWorkflowSteer(workflows);
    const selected = steer.web[0];
    if (!selected) {
      loading.body.textContent =
        "No current workflow version allows the web form entry surface.";
      return;
    }
    const verificationStageId = "reviewing-implementation";
    const state = {
      verification: false,
      file_budget: false,
      path_claims: false,
      path_survey: false,
      approval_on_done: false,
      deployment: false,
      verification_target: "",
    };
    const directWorkflow = ["dash", "blitz"].includes(selected.id);
    const pathSurveyPolicy = selected.definition?.policies?.path_survey ||
      (directWorkflow ? "required" : null);
    state.path_survey = pathSurveyPolicy === "required";
    const verificationAvailable = Boolean(
      catalog.plans.length || catalog.methods.length,
    );
    const title = el(documentNode, "input", "item-form-control");
    title.type = "text";
    title.maxLength = 100;
    title.required = true;
    const instruction = el(documentNode, "textarea", "item-form-control");
    instruction.required = true;
    instruction.rows = 3;
    const render = () => {
      const host = el(documentNode, "div", "item-new");
      const head = el(
        documentNode, "div", "page-head item-new-heading",
      );
      const copy = el(documentNode, "div", "h");
      copy.appendChild(el(
        documentNode,
        "h1",
        "title",
        `New ${selected.name || selected.id}`,
      ));
      copy.appendChild(el(
        documentNode, "p", "subtitle", steer.copy,
      ));
      head.appendChild(copy);
      const cancel = el(documentNode, "a", "item-button", "Cancel");
      cancel.href = buildUniverseRoute("items", String(projectId));
      const actions = el(documentNode, "div", "head-actions");
      actions.appendChild(cancel);
      head.appendChild(actions);
      host.appendChild(head);

      const form = el(documentNode, "form", "item-form");
      form.appendChild(itemIntakeField(documentNode, "Title", title));
      const instructionHelp = el(
        documentNode,
        "span",
        "item-form-help",
        `This is the whole spec. If the work turns out bigger than it looks, ` +
        `the agent stops, records findings, files an Issue, and cancels this ` +
        `${selected.name || selected.id} with a link.`,
      );
      form.appendChild(itemIntakeField(
        documentNode, "Instruction", instruction, instructionHelp,
      ));
      const projectField = el(documentNode, "div", "item-form-field");
      projectField.appendChild(el(
        documentNode, "span", "item-form-label", "Project",
      ));
      projectField.appendChild(el(
        documentNode,
        "div",
        "item-project-value",
        `${project?.emoji ? `${project.emoji} ` : ""}` +
        `${project?.slug || project?.name || String(projectId)}`,
      ));
      form.appendChild(projectField);

      const settings = workflowPanel(documentNode, "Settings");
      settings.body.className += " item-stack";
      const allow = new Set(
        selected.definition?.policies?.item_posture_allowlist || [],
      );
      const rows = [
        [
          "verification", "✓", "Verification",
          state.verification
            ? `choose a plan or ad hoc case — runs at ${verificationStageId}`
            : verificationAvailable
              ? `when off, we rely on agent self-check at ${verificationStageId}`
              : "no plans or ad hoc methods are available for this project",
        ],
        [
          "file_budget", "▤", "File Budget",
          `plans the files this ${selected.name || selected.id} touches ` +
          "for sizing and conflict evidence before implementation",
        ],
        [
          "path_claims", "⛉", "Path claims",
          `reserves the files this ${selected.name || selected.id} touches, ` +
          "so overlapping work serializes instead of colliding at merge",
        ],
        [
          "path_survey", "⌁", "Path survey",
          `checks the files this ${selected.name || selected.id} expects to ` +
          "touch and re-checks the declared set immediately before merge",
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
        const directSurvey = key === "path_survey" && directWorkflow;
        if (!allow.has(key) && !(key === "approval_on_done" && allow.has("approval")) && !directSurvey) {
          continue;
        }
        settings.body.appendChild(itemPostureToggle(
          documentNode,
          icon,
          label,
          note,
          state,
          key,
          render,
          key === "verification" && state.verification
            ? verificationChoiceSelect(documentNode, catalog, state)
            : null,
          key !== "verification" || verificationAvailable,
          key === "path_survey" && pathSurveyPolicy === "required",
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
        if (state.verification && !state.verification_target) {
          outcome.className = "item-form-outcome error";
          outcome.textContent =
            "Choose a verification plan or ad hoc method.";
          return;
        }
        const posture = {};
        if (state.verification) {
          const [kind, id] = state.verification_target.split(":", 2);
          posture.verification = kind === "plan"
            ? { kind: "plan", plan_id: Number(id) }
            : { kind: "ad_hoc", method_id: id };
        }
        for (const key of [
          "file_budget", "path_claims", "path_survey", "deployment",
        ]) {
          if (key === "path_survey" && pathSurveyPolicy === "required") {
            continue;
          }
          if (state[key]) posture[key] = true;
        }
        if (state.approval_on_done) {
          posture[allow.has("approval_on_done")
            ? "approval_on_done" : "approval"] = true;
        }
        submit.disabled = true;
        outcome.className = "item-form-outcome";
        outcome.textContent = "Creating…";
        let result;
        try {
          result = await callFunction(context.client, "items.create", {
            title: cleanTitle,
            instruction: cleanInstruction,
            project: String(project?.slug || project?.id || projectId),
            workflow: selected.id,
            entry_surface: "web_form",
            workflow_posture: posture,
          });
        } catch (error) {
          result = {
            status: 0,
            envelope: {
              success: false,
              error: { message: String(error) },
            },
          };
        }
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
  }).catch((error) => {
    if (!context.isMounted()) return;
    loading.body.replaceChildren();
    renderError(loading.body, {
      status: 0,
      envelope: {
        success: false,
        error: { message: String(error) },
      },
    });
  });
}
