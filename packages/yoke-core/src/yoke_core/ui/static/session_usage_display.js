/**
 * Show what a session consumed without implying a precision it lacks.
 *
 * The control plane ships derived figures rather than the stored reading,
 * so pricing happens once server-side and a card, a table and a summed
 * tile cannot disagree. What is left here is presentation, and its whole
 * job is distinguishing three states an operator would otherwise conflate:
 * a measured figure, a figure computed from an incomplete reading, and no
 * measurement at all. The last is never drawn as a zero — a session that
 * has not been read yet did not run for free.
 *
 * The dollar figure is an estimate of API-equivalent spend. A session run
 * under a subscription plan spends that plan's own meters instead, and no
 * published conversion turns one into the other, so the label says so
 * everywhere the number appears.
 */

// Marks a figure computed from an incomplete reading. Trails the value so a
// column of numbers still lines up on its digits.
export const PARTIAL_MARK = "~";

// What a session with no reading at all shows.
export const UNREAD_DISPLAY = "—";

const COMPLETE = "complete";

function finiteCount(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function compactTokens(value) {
  const count = finiteCount(value);
  if (count === null) return "";
  const scale = count >= 1_000_000
    ? [1_000_000, "m"]
    : count >= 1_000 ? [1_000, "k"] : null;
  if (!scale) return String(Math.round(count));
  const scaled = count / scale[0];
  const precision = scaled < 10 ? 1 : 0;
  return `${scaled.toFixed(precision).replace(/\.0$/, "")}${scale[1]}`;
}

export function compactUsd(value) {
  const amount = finiteCount(value);
  if (amount === null) return "";
  if (amount < 1) return `$${amount.toFixed(2)}`;
  if (amount < 100) return `$${amount.toFixed(2)}`.replace(/\.?0+$/, "");
  return `$${Math.round(amount).toLocaleString("en-US")}`;
}

function mark(status) {
  return status && status !== COMPLETE ? PARTIAL_MARK : "";
}

export function sessionTokensDisplay(row) {
  const tokens = compactTokens(row?.usage_tokens);
  return tokens ? `${tokens}${mark(row?.usage_status)}` : UNREAD_DISPLAY;
}

export function sessionCostDisplay(row) {
  const cost = compactUsd(row?.usage_cost_usd);
  return cost ? `${cost}${mark(row?.usage_cost_status)}` : UNREAD_DISPLAY;
}

export function sessionUsageIsPartial(row) {
  return Boolean(
    mark(row?.usage_status) || (row?.usage_cost_usd && mark(row?.usage_cost_status)),
  );
}

/**
 * Sum the sessions a tile is actually showing, and say how many that was.
 *
 * A machine tile answers for the rows currently on the page, not for the
 * machine's whole history, so the scope travels with the total: `covered`
 * counts the rows that carried a reading and `total` counts the rows the
 * sum ranged over. A tile that reports 1.2m tokens over 2 of 5 sessions is
 * telling the truth; one that reports 1.2m alone is not.
 */
export function summarizeSessionUsage(rows) {
  const scoped = Array.isArray(rows) ? rows : [];
  let tokens = 0;
  let cost = 0;
  let covered = 0;
  let costed = 0;
  let partial = false;
  for (const row of scoped) {
    const rowTokens = finiteCount(row?.usage_tokens);
    const rowCost = finiteCount(row?.usage_cost_usd);
    if (rowTokens !== null) {
      tokens += rowTokens;
      covered += 1;
      if (mark(row?.usage_status)) partial = true;
    }
    if (rowCost !== null) {
      cost += rowCost;
      costed += 1;
      if (mark(row?.usage_cost_status)) partial = true;
    }
  }
  // A sum missing some of its members is itself partial, whatever each
  // member's own reading said.
  if (covered < scoped.length || costed < covered) partial = true;
  return {
    tokens,
    cost,
    covered,
    costed,
    total: scoped.length,
    partial: covered > 0 && partial,
  };
}

export function usageSummaryLabel(summary) {
  if (!summary || summary.covered === 0) {
    return summary?.total
      ? `no consumption recorded for ${summary.total} sessions`
      : "";
  }
  const suffix = summary.partial ? PARTIAL_MARK : "";
  const money = summary.costed > 0
    ? ` · ${compactUsd(summary.cost)}${suffix}`
    : "";
  return `${compactTokens(summary.tokens)}${suffix}${money}`;
}

/**
 * Say how many sessions each half of the total was drawn from.
 *
 * Token coverage and cost coverage are different counts and routinely
 * differ: a session on a model nobody has researched a price for reports
 * its tokens and contributes nothing to the dollar figure. Reporting only
 * "2 of 13 sessions reported" beside a dollar total invites reading that
 * total as the spend of both sessions when one of them was never priced,
 * so the priced count is stated separately whenever it differs.
 */
export function usageSummaryScope(summary) {
  if (!summary || !summary.total) return "";
  const reported = `${summary.covered} of ${summary.total} sessions reported`;
  if (!summary.costed || summary.costed === summary.covered) return reported;
  return `${reported} · ${summary.costed} priced`;
}
