"""Serve production thumbnail components with extreme-aspect fixture images.

Run through ``yoke dev run -- env YOKE_ENV=render-proof python3 -m
runtime.api.tools.evidence_thumbnail_review``. Open the printed tokened URL,
then /thumbnail-review. The existing review server owns assets, authentication,
universe provenance, and /served-build; this tool adds only a fixture route.
"""

from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse

from runtime.api.tools.serve_workbench_for_review import (
    _free_port,
    prepare_review_database,
)
from yoke_core.ui.server import create_ui_app, mint_session_token
from yoke_core.ui.served_source_identity import served_build_identity
from yoke_core.ui.served_universe_connection import serving_connection


def main() -> None:
    prepare_review_database()
    port = _free_port()
    token = mint_session_token()
    app = create_ui_app(token, port=port)
    fixture_path = Path(__file__).with_suffix(".html")
    environment, _ = serving_connection()

    @app.get("/thumbnail-review")
    def thumbnails() -> HTMLResponse:
        return HTMLResponse(
            fixture_path.read_text()
            .replace("{{environment}}", str(environment))
            .replace("{{commit}}", served_build_identity()),
            headers={"Cache-Control": "no-store"},
        )

    print(f"review url: http://127.0.0.1:{port}/?token={token}", flush=True)
    print("fixture route: /thumbnail-review", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
