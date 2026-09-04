// Machines waiting for an org admin's answer, rendered where the machines
// are.
//
// A machine authorization is answered beside the machine it admits: which
// machine asked, who asked for it, and the one-time code the person sitting
// at it is reading off their terminal. None of that belongs in an Inbox row
// of its own, so the gate lives at the top of this page and the Inbox row
// links here.
//
// Approving admits the machine; it never makes the approver its owner. A
// machine belongs to the actor who installed Yoke and authenticated on it —
// the actor this row names as its requester — so an admin may answer for
// someone else's machine without taking it.

import { el, loadScopedSection, section } from "./universe_view_support.js";
import {
  appendDecisionRow,
  createDecisionResolver,
} from "./inbox_rows.js";

export function renderMachineApprovalsView(context, main) {
  const documentNode = context.document;
  const panel = section(
    documentNode, "Machines waiting for approval", { showRaw: false },
  );
  panel.children[1].className += " inbox-stack";
  main.replaceChildren(panel);

  const load = () => {
    // A failed read must be visible even when the last load had nothing to
    // show, so the panel comes back before every read and the render below
    // is the only thing that hides it again.
    panel.hidden = false;
    return loadScopedSection(
      context,
      panel,
      [{ functionId: "inbox.list", payload: {} }],
      (body, calls) => {
        const rows = calls[0].envelope.result.machine_approvals || [];
        // Nothing waiting is the ordinary state of this page, and a standing
        // empty panel above the machines would be noise rather than news.
        panel.hidden = rows.length === 0;
        panel.setCount(rows.length || null);
        if (!rows.length) return;
        body.appendChild(el(
          documentNode,
          "p",
          "inbox-panel-hint",
          "The machine stays with whoever installed Yoke on it, not with you.",
        ));
        for (const row of rows) {
          appendDecisionRow(context, body, row, resolve, null);
        }
      },
    );
  };

  const resolve = createDecisionResolver(context, load);

  load();
}
