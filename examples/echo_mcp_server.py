import json
import sys
from typing import Any


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        if "id" not in message:
            continue
        method = message.get("method")
        if method == "initialize":
            respond(message["id"], {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "yizutt-echo-mcp", "version": "0.1.0"},
            })
        elif method == "tools/list":
            respond(message["id"], {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Return the provided text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            })
        elif method == "tools/call":
            params = message.get("params") or {}
            arguments = params.get("arguments") or {}
            text = str(arguments.get("text", ""))
            respond(message["id"], {"content": [{"type": "text", "text": text}], "isError": False})
        else:
            respond_error(message["id"], -32601, f"method not found: {method}")
    return 0


def respond(message_id: Any, result: dict[str, Any]) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}, ensure_ascii=False), flush=True)


def respond_error(message_id: Any, code: int, message: str) -> None:
    print(
        json.dumps({"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}, ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
