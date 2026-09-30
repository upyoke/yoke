'use strict';

/**
 * Active interaction action handlers: click, fill_form, type, select, delay,
 * wait_for, ready.
 *
 * Each handler takes (page, step, options[, refMap]) and returns
 * { success: boolean } or throws an Error.
 */

const {
  getVisibleText,
  resolveTarget,
  resolvePresenceTarget,
} = require('./target-helpers');

// Default timeout for scenario interaction actions.
const DEFAULT_TIMEOUT_MS = 5000;

// How often a readiness wait re-reads the page while its budget lasts.
const POLL_INTERVAL_MS = 100;

/**
 * Execute a click action.
 */
async function executeClick(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.click({ timeout });
  return { success: true };
}

/**
 * Execute a fill_form action.
 * Iterates over fields object, filling each target with its value.
 */
async function executeFillForm(page, step, options, refMap) {
  const fields = step.fields;
  if (!fields || typeof fields !== 'object') {
    throw new Error('fill_form action requires a fields object');
  }

  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;

  for (const [selector, value] of Object.entries(fields)) {
    const locator = resolveTarget(page, selector, refMap);
    await locator.fill(String(value), { timeout });
  }
  return { success: true };
}

/**
 * Execute a delay action.
 * Waits for a specified duration (pure time delay, no DOM target).
 */
async function executeDelay(page, step) {
  const ms = step.duration || step.duration_ms || 1000;
  await page.waitForTimeout(ms);
  return { success: true };
}

/**
 * Execute a wait_for action.
 *
 * Waits for the target to be visible within timeout. This asks about
 * presence, so it resolves the first match: a selector naming a repeated
 * component is a legitimate way to wait for a list to render, and strict
 * resolution refused it for matching more than once.
 */
async function executeWaitFor(page, step, options, refMap) {
  const locator = resolvePresenceTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.waitFor({ state: 'visible', timeout });
  return { success: true };
}

/**
 * Execute a ready action: wait until a page has finished loading its content.
 *
 * `wait_for` waits for something to appear. Readiness is the opposite
 * question -- waiting for the placeholder to go away -- and without it a
 * capture or an assertion lands on a skeleton that has already rendered its
 * container. A step states the placeholder either as a selector (`target`)
 * or as the text it shows (`text`, matched case-insensitively against the
 * visible document), or both; both must be gone before the step passes.
 *
 * It refuses a step naming neither, because a readiness step with nothing to
 * wait for would pass instantly and read as proof that the page had settled.
 */
async function executeReady(page, step, options, refMap) {
  const hasTarget = typeof step.target === 'string' && step.target.trim();
  const hasText = typeof step.text === 'string' && step.text.trim();
  if (!hasTarget && !hasText) {
    throw new Error(
      'ready action requires target, text, or both: a readiness step naming '
      + 'no loading indicator would pass instantly and prove nothing. Give '
      + 'target a loading selector (".skeleton"), text the placeholder\'s '
      + 'own words ("Loading"), or both.'
    );
  }

  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  const deadline = Date.now() + timeout;

  if (hasTarget) {
    // `hidden` is satisfied by detached as well as invisible, which is what
    // "no longer loading" means for a placeholder the app removes.
    await resolvePresenceTarget(page, step.target, refMap)
      .waitFor({ state: 'hidden', timeout });
  }

  if (hasText) {
    const needle = step.text.trim().toLowerCase();
    let seen = '';
    while (true) {
      seen = await getVisibleText(page);
      if (!seen.toLowerCase().includes(needle)) {
        return { success: true };
      }
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw new Error(
          `ready timed out after ${timeout}ms: the page still shows `
          + `${JSON.stringify(step.text)}, so its content has not loaded. `
          + 'Raise timeout_ms if the screen is legitimately slower than '
          + 'that, or correct the text if the page never shows it.'
        );
      }
      await page.waitForTimeout(Math.min(POLL_INTERVAL_MS, remaining));
    }
  }

  return { success: true };
}

/**
 * Execute a type action (keyboard input).
 */
async function executeType(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.click({ timeout });
  await page.keyboard.type(step.value || '', { delay: step.delay || 0 });
  return { success: true };
}

/**
 * Execute a select action.
 */
async function executeSelect(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.selectOption(step.value, { timeout });
  return { success: true };
}

module.exports = {
  executeClick,
  executeFillForm,
  executeDelay,
  executeWaitFor,
  executeReady,
  executeType,
  executeSelect,
};
