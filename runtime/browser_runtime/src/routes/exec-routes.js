'use strict';

/**
 * Route module for step execution operations.
 *
 * Registers:
 *   POST /api/exec/step
 *
 * Follows the route registration pattern from snapshot-routes.js:
 *   module.exports = function(app, browserManager) { ... }
 */

const { executeStep } = require('../step-executor');

/**
 * @param {import('express').Application} app
 * @param {Object} browserManager
 */
function registerExecRoutes(app, browserManager) {
  // POST /api/exec/step
  // Request body: { step: object, baseUrl: string, outputDir?: string }
  // Response: { success: true, data: { success, duration_ms, error?, artifacts? } }
  app.post('/api/exec/step', async (req, res) => {
    try {
      const { step, baseUrl, outputDir } = req.body || {};

      if (!step) {
        return res.status(400).json({
          success: false,
          error: 'step is required in request body',
        });
      }

      if (!baseUrl) {
        return res.status(400).json({
          success: false,
          error: 'baseUrl is required in request body',
        });
      }

      // Get the current page (or create one if needed)
      const page = await browserManager.getPage();

      const options = { baseUrl };
      if (outputDir) options.outputDir = outputDir;

      const result = await executeStep(page, step, options);

      res.json({
        success: true,
        data: result,
      });
    } catch (err) {
      res.status(500).json({
        success: false,
        error: err.message,
      });
    }
  });
}

module.exports = registerExecRoutes;
