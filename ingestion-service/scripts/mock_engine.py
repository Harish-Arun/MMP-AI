"""
Mock mmp-ai-engine server for local development.

Listens on port 8000 and accepts POST /api/v1/workflows/trigger,
printing each received payload to stdout and returning 202 Accepted.

Usage:
    python scripts/mock_engine.py
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class MockEngineHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/v1/workflows/trigger":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                print("\n[mock-engine] Trigger received:")
                print(json.dumps(payload, indent=2))
            except Exception:
                print(f"[mock-engine] Raw body: {body}")

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "accepted"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default Apache-style access log, we print our own
        pass


if __name__ == "__main__":
    host, port = "0.0.0.0", 8000
    server = HTTPServer((host, port), MockEngineHandler)
    print(f"[mock-engine] Listening on http://{host}:{port}")
    print("[mock-engine] Waiting for Lambda triggers...\n")
    server.serve_forever()
