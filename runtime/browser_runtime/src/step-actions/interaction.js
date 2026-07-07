'use strict';

/**
 * Active interaction action handlers: click, fill_form, type, select, delay, wait_for.
 *
 * Each handler takes (page, step, options[, refMap]) and returns
 * { success: boolean } or throws an Error.
 */

const { resolveTarget } = require('./target-helpers');

// Default timeout for scenario interaction actions.
const DEFAULT_TIMEOUT_MS = 5000;

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
 * Waits for the target element to be visible within timeout.
 */
async function executeWaitFor(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.waitFor({ state: 'visible', timeout });
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
  executeType,
  executeSelect,
};
