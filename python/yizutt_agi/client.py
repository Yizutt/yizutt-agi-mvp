import json
import os
import subprocess
from pathlib import Path


class YizuttRuntimeClient:
    def __init__(self, binary: str | Path = "target/debug/yizutt-runtime", addr: str | None = None) -> None:
        self.binary = str(binary)
        self.addr = addr or os.getenv("YIZUTT_RUNTIME_ADDR", "http://127.0.0.1:50200")

    def submit(self, task: str, session_id: str = "default", context: dict | None = None) -> dict:
        completed = subprocess.run(
            [
                self.binary,
                "submit",
                "--addr",
                self.addr,
                "--session",
                session_id,
                "--task",
                task,
                "--context-json",
                json.dumps(context or {}, ensure_ascii=False),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    def status(self) -> list[dict]:
        completed = subprocess.run(
            [self.binary, "status", "--addr", self.addr],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)
