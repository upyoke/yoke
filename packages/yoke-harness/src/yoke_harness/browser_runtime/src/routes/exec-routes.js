'use strict';

/**
 * Route module for step execution operations.
 *
 * Registers:
 *   POST /api/exec/page        -- open the page a run owns, at a stated size
 *   POST /api/exec/page/close  -- close it
 *   POST /api/exec/step        -- run one step against an owned page
 *
 * A run addresses its own page by id. Steps used to land on whichever page
 * the daemon happened to be holding, so a run could inherit the route and the
 * viewport of the run before it and describe a screen it never asked for.
 *
 * Follows the route registration pattern from snapshot-routes.js:
 *   module.exports = function(app, browserManager) { ... }
 */

const { executeStep } = require('../step-runner');

/**
 * @param {import('express').Application} app
 * @param {Object} browserManager
 */
function registerExecRoutes(app, browserManager) {
  // POST /api/exec/page
  // Request body: { viewport: { width, height }, pageId?: string }
  // Response: { success: true, data: { pageId, viewport, opened } }
  app.post('/api/exec/page', async (req, res) => {
    try {
      const { viewport, pageId } = req.body || {};
      const result = await browserManager.openOwnedPage(viewport, pageId);
      res.json({ success: true, data: result });
    } catch (err) {
      res.status(400).json({ success: false, error: err.message });
    }
  });

  // POST /api/exec/page/close
  // Request body: { pageId: string }
  // Response: { success: true, data: { closed: true } }
  app.post('/api/exec/page/close', async (req, res) => {
    try {
      const { pageId } = req.body || {};
      if (!pageId) {
        return res.status(400).json({
          success: false,
          error: 'pageId is required in request body',
        });
      }
      const result = await browserManager.closeOwnedPage(pageId);
      res.json({ success: true, data: result });
    } catch (err) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  // POST /api/exec/step
  // Request body: { step: object, baseUrl: string, pageId: string, outputDir?: string }
  // Response: { success: true, data: { success, duration_ms, viewport, url,
  //   error?, artifacts?, vacuous_absence? } }
  app.post('/api/exec/step', async (req, res) => {
    try {
      const { step, baseUrl, outputDir, pageId } = req.body || {};

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

      if (!pageId) {
        return res.status(400).json({
          success: false,
          error: 'pageId is required in request body: a step runs on the page '
            + 'its run owns, opened with POST /api/exec/page',
        });
      }

      // The run's own page, or a named refusal -- never a substitute.
      const page = browserManager.ownedPage(pageId);

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
