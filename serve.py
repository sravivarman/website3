"""
serve.py  —  Local preview server for the built conference site.

Usage:
    uv run python serve.py          # serves on http://localhost:8000
    uv run python serve.py 9000     # serves on http://localhost:9000
    uv run python serve.py 9000 dist

This serves the dist/ directory (the default output of build.py) using Python's
built-in HTTP server — no additional dependencies required.
Press Ctrl+C to stop.
"""

import http.server
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT_BUILD_DIR = ROOT / "dist"
DEFAULT_PORT = 8000


def main() -> None:
    # Allow an optional port argument: `uv run python serve.py 9000`
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    build_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BUILD_DIR
    if not build_dir.is_absolute():
        build_dir = ROOT / build_dir

    if not build_dir.exists():
        sys.exit(
            f"Error: {build_dir.relative_to(ROOT)}/ directory not found.\n"
            "Run  uv run python build.py  first to generate the site."
        )

    # Change working directory to the built site so the server resolves paths correctly.
    os.chdir(build_dir)

    url = f"http://localhost:{port}"
    print(f"Serving conference site from  {build_dir.relative_to(ROOT)}/  at  {url}")
    print("Press Ctrl+C to stop.\n")

    # Open the browser automatically
    webbrowser.open(url)

    handler = http.server.SimpleHTTPRequestHandler
    with http.server.HTTPServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
