import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockModelHandler(BaseHTTPRequestHandler):
    server_version = "YizuttMockModel/0.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {}
        prompt = str(payload.get("prompt") or payload.get("input") or "")
        response = {"text": model_response(prompt)}
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"mock-model {self.address_string()} - {fmt % args}", flush=True)


def model_response(prompt: str) -> str:
    if "Tool protocol:" in prompt:
        observations = prompt.split("Tool observations so far:", 1)[-1]
        if '"tool": "read_file"' not in observations and '"tool":"read_file"' not in observations:
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "name": "read_file",
                            "arguments": {"path": "README.md", "max_chars": 800},
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "final_answer": (
                    "Local mock completed the runtime loop, used read_file on README.md, "
                    "and returned a deterministic answer."
                )
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "answer": "Local mock completed one task-memory-skill loop.",
            "reusable_steps": [
                "Start a local model endpoint.",
                "Run the Yizutt runtime with provider=local.",
                "Submit a task and capture the returned trace.",
                "Persist the result to working memory and save a skill file.",
            ],
            "skill_name": "local-mock-e2e",
            "skill_description": "Reusable local mock path for validating the Yizutt loop.",
        },
        ensure_ascii=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic local model endpoint for Yizutt demos.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50990)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockModelHandler)
    print(f"local mock model listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
