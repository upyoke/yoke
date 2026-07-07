'use strict';

/**
 * Capture action handler: screenshot.
 *
 * executeScreenshot(page, step, options) -> { success: true, artifacts?: string[] }
 */

const path = require('path');

/**
 * Execute a screenshot action.
 * Captures a screenshot when capture is true, returns the path in artifacts.
 */
async function executeScreenshot(page, step, options) {
  if (!step.capture) {
    return { success: true };
  }

  const outputDir = options.outputDir || '/tmp';
  const timestamp = Date.now();
  const screenshotPath = path.join(outputDir, `screenshot-${timestamp}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: !!step.fullPage });
  return { success: true, artifacts: [screenshotPath] };
}

module.exports = { executeScreenshot };
