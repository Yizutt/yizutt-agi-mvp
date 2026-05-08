import json
import subprocess
import threading
from typing import Any


MCP_PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, command: list[str], timeout_secs: float = 15.0) -> None:
        if not command:
            raise ValueError("MCP command is empty")
        self.command = [str(part) for part in command]
        self.timeout_secs = timeout_secs
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def __enter__(self) -> "McpStdioClient":
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "yizutt-agi", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return self._read_response(request_id)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _write(self, message: dict[str, Any]) -> None:
        process = self._process()
        if process.stdin is None:
            raise McpError("MCP stdin is not available")
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        process = self._process()
        if process.stdout is None:
            raise McpError("MCP stdout is not available")
        deadline = threading.Timer(self.timeout_secs, self._kill_on_timeout)
        deadline.start()
        try:
            while True:
                line = process.stdout.readline()
                if not line:
                    stderr = process.stderr.read() if process.stderr else ""
                    raise McpError(f"MCP server exited before response: {stderr.strip()}")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise McpError(f"invalid MCP JSON message: {line.strip()}") from exc
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise McpError(json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result", {})
                return result if isinstance(result, dict) else {"value": result}
        finally:
            deadline.cancel()

    def _kill_on_timeout(self) -> None:
        process = self.process
        if process and process.poll() is None:
            process.kill()

    def _process(self) -> subprocess.Popen[str]:
        if self.process is None:
            raise McpError("MCP client is not started")
        return self.process
