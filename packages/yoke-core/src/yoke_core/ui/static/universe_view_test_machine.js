import {
  callFunction,
  el,
  renderError,
} from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  machineDefinitionList as definitionList,
  machinePanel as panel,
  machineVerificationCallout as verificationCallout,
} from "./test_machine_view_primitives.js";
import {
  machineSettingsDialog as settingsDialog,
} from "./test_machine_settings_dialog.js";
import {
  availabilityPanel,
  methodsPanel,
  operationsPanel,
  receiptPanel,
  secretPanel,
} from "./test_machine_detail_panels.js";

function renderDetail(context, main, detail, reload, showFleet = null) {
  const documentNode = context.document;
  const header = el(
    documentNode,
    "div",
    "page-head test-machine-head",
  );
  const copy = el(documentNode, "div", "h test-machine-head-copy");
  copy.appendChild(el(
    documentNode, "h1", "title", detail.display_name || "Test Mac",
  ));
  copy.appendChild(el(
    documentNode,
    "p",
    "subtitle muted",
    `${detail.capability_type} · composite · ${detail.project}`,
  ));
  header.appendChild(copy);
  const actions = el(
    documentNode,
    "div",
    "head-actions test-machine-actions",
  );
  if (showFleet) {
    const fleet = el(documentNode, "button", "btn", "All machines");
    fleet.type = "button";
    fleet.addEventListener("click", showFleet);
    actions.appendChild(fleet);
  }
  const edit = el(documentNode, "button", "btn", "Edit settings");
  edit.type = "button";
  edit.addEventListener("click", () => {
    const modal = settingsDialog(
      context,
      detail,
      () => main.removeChild(modal),
      reload,
    );
    main.appendChild(modal);
  });
  actions.appendChild(edit);
  const verify = el(documentNode, "button", "btn primary", "Verify now");
  verify.type = "button";
  const verifyStatus = el(
    documentNode, "span", "test-machine-action-status",
  );
  verifyStatus.setAttribute("role", "status");
  verifyStatus.setAttribute("aria-live", "polite");
  verify.addEventListener("click", async () => {
    verify.disabled = true;
    verify.setAttribute("aria-busy", "true");
    verify.textContent = "Verifying…";
    verifyStatus.textContent = "";
    verifyStatus.setAttribute("role", "status");
    verifyStatus.setAttribute("aria-live", "polite");
    let result;
    try {
      result = await callFunction(
        context.client,
        "test_machine.verify",
        { project: detail.project, machine: detail.machine },
      );
    } catch (error) {
      result = {
        envelope: {
          success: false,
          error: { message: String(error) },
        },
      };
    }
    if (!result.envelope?.success) {
      verify.disabled = false;
      verify.setAttribute("aria-busy", "false");
      verify.textContent = "Verify now";
      verifyStatus.setAttribute("role", "alert");
      verifyStatus.setAttribute("aria-live", "assertive");
      verifyStatus.textContent =
        result.envelope?.error?.message || "Verification failed.";
      return;
    }
    reload();
  });
  actions.appendChild(verify);
  actions.appendChild(verifyStatus);
  header.appendChild(actions);
  const columns = el(
    documentNode,
    "div",
    "split test-machine-columns",
  );
  const left = el(documentNode, "div", "stack test-machine-stack");
  const connection = panel(documentNode, "Connection and behavior");
  connection.body.classList.add("test-machine-kv-body");
  const baselineSummary = el(documentNode, "span");
  for (const [index, baseline] of detail.host_baselines.entries()) {
    if (index > 0) {
      baselineSummary.appendChild(el(documentNode, "span", null, " · "));
    }
    baselineSummary.appendChild(el(
      documentNode, "span", "mono", baseline,
    ));
  }
  const baselineExplanation = el(
    documentNode,
    "span",
    "test-machine-baseline-explanation",
    " — registered operations on ",
  );
  baselineExplanation.appendChild(el(
    documentNode, "span", "mono", detail.runner_id,
  ));
  baselineExplanation.appendChild(el(
    documentNode,
    "span",
    null,
    ", run inside the lease; each verifies the branch-determining state it promises and emits that verification as evidence",
  ));
  baselineSummary.appendChild(baselineExplanation);
  connection.body.appendChild(definitionList(documentNode, [
    ["Resource name", detail.settings.resource_name],
    ["Host", el(documentNode, "span", "mono", detail.settings.host)],
    ["User", el(documentNode, "span", "mono", detail.settings.user)],
    ["Host kind", el(documentNode, "span", "mono", detail.settings.host_kind)],
    ["Features", detail.features.join(" · ")],
    ["Host baselines", baselineSummary],
    ["Operating notes", detail.settings.operating_notes],
  ]));
  left.appendChild(connection.root);
  left.appendChild(secretPanel(documentNode, detail));
  const right = el(documentNode, "div", "stack test-machine-stack");
  right.appendChild(availabilityPanel(documentNode, detail));
  right.appendChild(methodsPanel(documentNode, detail));
  right.appendChild(receiptPanel(documentNode, detail));
  right.appendChild(operationsPanel(documentNode, detail));
  columns.appendChild(left);
  columns.appendChild(right);
  main.replaceChildren(
    header,
    verificationCallout(documentNode, detail),
    columns,
  );
}

function lastOperationSummary(detail) {
  const [latest] = detail.operations || [];
  if (!latest) return "";
  return `last ${latest.operation.replace("_", " ")}: ${latest.status}`;
}


function renderMissing(documentNode, main, project) {
  const missing = panel(documentNode, "Capability");
  missing.body.appendChild(el(
    documentNode,
    "p",
    "empty",
    "No test machines are configured for this project.",
  ));
  const back = el(documentNode, "a", "btn", "Back to capabilities");
  back.href = buildUniverseRoute("capabilities", project);
  missing.body.appendChild(back);
  main.replaceChildren(missing.root);
}

async function loadMachineDetail(
  context,
  main,
  project,
  machine,
  navigation,
  showFleet,
) {
  const documentNode = context.document;
  main.replaceChildren(el(documentNode, "p", "empty", "loading machine…"));
  let result;
  try {
    result = await callFunction(
      context.client,
      "test_machine.get",
      { project, machine },
    );
  } catch (error) {
    result = {
      status: 0,
      envelope: { success: false, error: { message: String(error) } },
    };
  }
  if (!context.isMounted()) return;
  if (!result.envelope?.success) {
    main.replaceChildren();
    renderError(main, result);
    return;
  }
  const detail = result.envelope.result;
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(detail.display_name);
  }
  renderDetail(
    context,
    main,
    detail,
    () => loadMachineDetail(
      context, main, project, detail.machine, navigation, showFleet,
    ),
    showFleet,
  );
}

function renderMachineChooser(
  context,
  main,
  project,
  machines,
  navigation,
) {
  const documentNode = context.document;
  const fleet = panel(documentNode, `Test Macs · ${machines.length}`);
  fleet.body.classList.add("stack");
  fleet.body.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Choose a machine to inspect, edit, or verify. Each machine has its own settings, receipt, and serial lease.",
  ));
  const showFleet = () => renderTestMachineDetail(
    context, main, project, navigation,
  );
  for (const detail of machines) {
    const choose = el(
      documentNode,
      "button",
      "doc-link test-machine-method",
    );
    choose.type = "button";
    choose.appendChild(el(
      documentNode,
      "strong",
      "dl-title",
      detail.display_name,
    ));
    choose.appendChild(el(
      documentNode,
      "small",
      "dl-sub",
      [
        detail.settings.host,
        detail.verification.status,
        lastOperationSummary(detail),
      ].filter(Boolean).join(" · "),
    ));
    choose.addEventListener("click", () => loadMachineDetail(
      context,
      main,
      project,
      detail.machine,
      navigation,
      showFleet,
    ));
    fleet.body.appendChild(choose);
  }
  main.replaceChildren(fleet.root);
}

export async function renderTestMachineDetail(
  context, main, project, navigation = {},
) {
  const documentNode = context.document;
  const reload = () => renderTestMachineDetail(
    context, main, project, navigation,
  );
  main.replaceChildren(el(documentNode, "p", "empty", "loading capability…"));
  let result;
  try {
    result = await callFunction(
      context.client,
      "test_machine.list",
      { project },
    );
  } catch (error) {
    result = {
      status: 0,
      envelope: {
        success: false,
        error: { message: String(error) },
      },
    };
  }
  if (!context.isMounted()) return;
  if (!result.envelope?.success) {
    main.replaceChildren();
    renderError(main, result);
    return;
  }
  const machines = result.envelope.result?.machines || [];
  if (!machines.length) {
    renderMissing(documentNode, main, project);
    return;
  }
  if (machines.length > 1) {
    if (typeof navigation.setDetailLabel === "function") {
      navigation.setDetailLabel("Test Macs");
    }
    renderMachineChooser(context, main, project, machines, navigation);
    return;
  }
  const detail = machines[0];
  if (typeof navigation.setDetailLabel === "function") {
    navigation.setDetailLabel(detail.display_name);
  }
  renderDetail(context, main, detail, reload);
}
