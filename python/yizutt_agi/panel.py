import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .capabilities import capability_matrix, evolution_plan
from .i18n import SUPPORTED_LANGUAGE_CODES, resolve_language


DEFAULT_RUNTIME_ADDR = "http://127.0.0.1:50200"
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PanelConfig:
    bind: str
    port: int
    runtime_addr: str
    runtime_bin: str
    project_root: Path
    web_root: Path
    runtime_home: Path
    memory_path: Path
    skills_root: Path
    history_path: Path
    cli_timeout_secs: int
    default_lang: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yizutt AGI local Web panel.")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50280)
    parser.add_argument("--runtime-addr", default=os.getenv("YIZUTT_RUNTIME_ADDR", DEFAULT_RUNTIME_ADDR))
    parser.add_argument("--runtime-bin", default=os.getenv("YIZUTT_RUNTIME_BIN", "target/debug/yizutt-runtime"))
    parser.add_argument("--runtime-home", default=os.getenv("YIZUTT_RUNTIME_HOME", ""))
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--memory-path", default=os.getenv("YIZUTT_MEMORY_PATH", ""))
    parser.add_argument("--skills-root", default=os.getenv("YIZUTT_SKILLS_ROOT", ""))
    parser.add_argument("--history-path", default=os.getenv("YIZUTT_PANEL_HISTORY_PATH", ""))
    parser.add_argument("--cli-timeout-secs", type=int, default=180)
    parser.add_argument(
        "--lang",
        default="",
        help="Default UI language short code: cnzh, twzh, en, ja, ko, ar, ru. Defaults to cnzh.",
    )
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    config = PanelConfig(
        bind=args.bind,
        port=args.port,
        runtime_addr=args.runtime_addr,
        runtime_bin=resolve_runtime_bin(project_root, args.runtime_bin),
        project_root=project_root,
        web_root=project_root / "web" / "panel",
        runtime_home=Path(args.runtime_home).expanduser() if args.runtime_home else project_root / ".yizutt" / "runtime",
        memory_path=Path(args.memory_path).expanduser() if args.memory_path else project_root / ".yizutt" / "memory" / "work.sqlite3",
        skills_root=Path(args.skills_root).expanduser() if args.skills_root else project_root / ".yizutt" / "skills",
        history_path=Path(args.history_path).expanduser() if args.history_path else project_root / ".yizutt" / "panel" / "history.sqlite3",
        cli_timeout_secs=args.cli_timeout_secs,
        default_lang=resolve_language(args.lang, argv0=sys.argv[0]),
    )

    server = ThreadingHTTPServer((config.bind, config.port), make_handler(config))
    print(f"Yizutt panel listening on http://{config.bind}:{config.port}", flush=True)
    print(f"Runtime default: {config.runtime_addr}", flush=True)
    print(f"Language default: {config.default_lang}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def make_handler(config: PanelConfig) -> type[BaseHTTPRequestHandler]:
    class PanelHandler(BaseHTTPRequestHandler):
        server_version = "YizuttPanel/0.1"

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"", "/"}:
                self.send_panel_html()
                return
            if parsed.path == "/api/status":
                self.send_json(lambda: api_status(config, parsed.query))
                return
            if parsed.path == "/api/memory":
                self.send_json(lambda: api_memory(config, parsed.query))
                return
            if parsed.path == "/api/skills":
                self.send_json(lambda: api_skills(config, parsed.query))
                return
            if parsed.path == "/api/history":
                self.send_json(lambda: api_history(config, parsed.query))
                return
            if parsed.path == "/api/history/run":
                self.send_json(lambda: api_history_run(config, parsed.query))
                return
            if parsed.path == "/api/runtime-tasks":
                self.send_json(lambda: api_runtime_tasks(config, parsed.query))
                return
            if parsed.path == "/api/capabilities":
                self.send_json(api_capabilities)
                return
            if parsed.path == "/api/evolution-plan":
                self.send_json(lambda: api_evolution_plan(parsed.query))
                return
            if parsed.path == "/api/config":
                self.send_json(lambda: api_config(config))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/submit":
                self.send_json(lambda: api_submit(config, self.read_json_body()))
                return
            if parsed.path == "/api/submit-stream":
                self.send_submit_stream(config, self.read_json_body())
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} - {fmt % args}", flush=True)

        def send_panel_html(self) -> None:
            path = config.web_root / "index.html"
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, f"missing {path}")
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, producer: Any) -> None:
            try:
                data = producer()
                status = HTTPStatus.OK
            except Exception as exc:
                data = {"ok": False, "error": str(exc)}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def send_submit_stream(self, config: PanelConfig, payload: dict[str, Any]) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                for event in api_submit_stream(config, payload):
                    self.write_sse(event)
            except BrokenPipeError:
                return
            except Exception as exc:
                self.write_sse({"type": "error", "error": str(exc)})
            finally:
                self.close_connection = True

        def write_sse(self, event: dict[str, Any]) -> None:
            body = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(body)
            self.wfile.flush()

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length > MAX_BODY_BYTES:
                raise ValueError("request body is too large")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

    return PanelHandler


def api_config(config: PanelConfig) -> dict[str, Any]:
    return {
        "ok": True,
        "runtime_addr": config.runtime_addr,
        "runtime_bin": config.runtime_bin,
        "runtime_home": str(config.runtime_home),
        "memory_path": str(config.memory_path),
        "skills_root": str(config.skills_root),
        "history_path": str(config.history_path),
        "default_language": config.default_lang,
        "supported_languages": list(SUPPORTED_LANGUAGE_CODES),
    }


def api_status(config: PanelConfig, query: str) -> dict[str, Any]:
    runtime_addr = query_value(query, "runtime_addr") or config.runtime_addr
    status_payload = run_runtime_json(config, ["status", "--addr", runtime_addr])
    workers = status_payload.get("workers", []) if isinstance(status_payload, dict) else status_payload
    return {
        "ok": True,
        "runtime_addr": runtime_addr,
        "workers": workers,
        "runtime": status_payload if isinstance(status_payload, dict) else {"workers": workers},
        "checked_at": int(time.time()),
    }


def api_submit(config: PanelConfig, payload: dict[str, Any]) -> dict[str, Any]:
    task = str(payload.get("task") or "").strip()
    if not task:
        raise ValueError("task is required")
    runtime_addr = str(payload.get("runtime_addr") or config.runtime_addr)
    session_id = str(payload.get("session_id") or "panel")
    context_json = normalize_context_json(payload.get("context_json"), payload.get("context"))
    run_id = history_start_run(config, runtime_addr, session_id, task, context_json)
    try:
        reply = run_runtime_json(
            config,
            [
                "submit",
                "--addr",
                runtime_addr,
                "--session",
                session_id,
                "--task",
                task,
                "--context-json",
                context_json,
            ],
        )
    except Exception as exc:
        history_finish_run(
            config,
            run_id,
            status="error",
            ok=False,
            exit_code=None,
            stderr=str(exc),
            trace_events=[{"type": "error", "error": str(exc)}],
        )
        raise
    trace_events = [{"type": "reply", "reply": reply}]
    history_finish_run(
        config,
        run_id,
        status="completed",
        ok=True,
        exit_code=0,
        stderr="",
        trace_events=trace_events,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "runtime_addr": runtime_addr,
        "session_id": session_id,
        "reply": reply,
        "completed_at": int(time.time()),
    }


def api_submit_stream(config: PanelConfig, payload: dict[str, Any]) -> Any:
    task = str(payload.get("task") or "").strip()
    if not task:
        raise ValueError("task is required")
    runtime_addr = str(payload.get("runtime_addr") or config.runtime_addr)
    session_id = str(payload.get("session_id") or "panel")
    context_json = normalize_context_json(payload.get("context_json"), payload.get("context"))
    args = [
        config.runtime_bin,
        "submit",
        "--stream",
        "--addr",
        runtime_addr,
        "--session",
        session_id,
        "--task",
        task,
        "--context-json",
        context_json,
    ]
    started_at = int(time.time())
    run_id = history_start_run(config, runtime_addr, session_id, task, context_json, started_at=started_at)
    trace_events = []
    started_event = {
        "type": "started",
        "run_id": run_id,
        "runtime_addr": runtime_addr,
        "session_id": session_id,
        "started_at": started_at,
    }
    trace_events.append(started_event)
    yield started_event
    process = subprocess.Popen(
        args,
        cwd=config.project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            event = {"type": "line", "text": line.rstrip("\n")}
            trace_events.append(event)
            yield event
        stderr = process.stderr.read() if process.stderr else ""
        code = process.wait(timeout=5)
    except Exception as exc:
        process.kill()
        error_event = {"type": "error", "error": str(exc)}
        trace_events.append(error_event)
        history_finish_run(
            config,
            run_id,
            status="error",
            ok=False,
            exit_code=None,
            stderr=str(exc),
            trace_events=trace_events,
        )
        raise
    finished_event = {
        "type": "finished",
        "ok": code == 0,
        "exit_code": code,
        "stderr": stderr.strip(),
        "completed_at": int(time.time()),
    }
    trace_events.append(finished_event)
    history_finish_run(
        config,
        run_id,
        status="completed" if code == 0 else "failed",
        ok=code == 0,
        exit_code=code,
        stderr=stderr.strip(),
        trace_events=trace_events,
        completed_at=finished_event["completed_at"],
    )
    yield finished_event


def api_memory(config: PanelConfig, query: str) -> dict[str, Any]:
    limit = clamp_int(query_value(query, "limit"), default=20, min_value=1, max_value=100)
    if not config.memory_path.exists():
        return {"ok": True, "exists": False, "path": str(config.memory_path), "items": []}

    conn = sqlite3.connect(f"file:{config.memory_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select id, session_id, role, content, meta_json, created_at
            from messages
            order by created_at desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "ok": True,
        "exists": True,
        "path": str(config.memory_path),
        "items": [memory_row_to_dict(row) for row in rows],
    }


def api_skills(config: PanelConfig, query: str) -> dict[str, Any]:
    limit = clamp_int(query_value(query, "limit"), default=20, min_value=1, max_value=100)
    if not config.skills_root.exists():
        return {"ok": True, "exists": False, "root": str(config.skills_root), "items": []}
    items = []
    for path in config.skills_root.glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        items.append(
            {
                "name": path.parent.name,
                "path": str(path),
                "description": frontmatter_value(text, "description"),
                "updated_at": int(stat.st_mtime),
                "preview": truncate(clean_preview(text), 600),
            }
        )
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return {
        "ok": True,
        "exists": True,
        "root": str(config.skills_root),
        "items": items[:limit],
    }


def api_history(config: PanelConfig, query: str) -> dict[str, Any]:
    limit = clamp_int(query_value(query, "limit"), default=20, min_value=1, max_value=100)
    if not config.history_path.exists():
        return {"ok": True, "exists": False, "path": str(config.history_path), "items": []}

    conn = sqlite3.connect(f"file:{config.history_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select id, session_id, runtime_addr, task, context_json, status, ok,
                   exit_code, trace_json, trace_summary, stderr, started_at,
                   completed_at, updated_at
            from panel_task_runs
            order by started_at desc, id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "ok": True,
        "exists": True,
        "path": str(config.history_path),
        "items": [history_row_to_dict(row, include_trace=False) for row in rows],
    }


def api_history_run(config: PanelConfig, query: str) -> dict[str, Any]:
    raw_id = query_value(query, "id")
    try:
        run_id = int(raw_id)
    except ValueError:
        return {"ok": False, "error": "history run id is required"}
    if not config.history_path.exists():
        return {"ok": False, "error": "history database has not been created"}

    conn = sqlite3.connect(f"file:{config.history_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            select id, session_id, runtime_addr, task, context_json, status, ok,
                   exit_code, trace_json, trace_summary, stderr, started_at,
                   completed_at, updated_at
            from panel_task_runs
            where id = ?
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"ok": False, "error": "history item not found"}
    return {
        "ok": True,
        "exists": True,
        "path": str(config.history_path),
        "item": history_row_to_dict(row, include_trace=True),
    }


def api_runtime_tasks(config: PanelConfig, query: str) -> dict[str, Any]:
    limit = clamp_int(query_value(query, "limit"), default=20, min_value=1, max_value=100)
    path = config.runtime_home / "tasks.jsonl"
    if not path.exists():
        return {"ok": True, "exists": False, "path": str(path), "items": []}
    items = run_runtime_json(config, ["tasks", "--home", str(config.runtime_home), "--limit", str(limit)])
    return {"ok": True, "exists": True, "path": str(path), "items": items}


def api_capabilities() -> dict[str, Any]:
    return capability_matrix()


def api_evolution_plan(query: str) -> dict[str, Any]:
    limit = clamp_int(query_value(query, "limit"), default=6, min_value=1, max_value=50)
    return evolution_plan(limit=limit)


def run_runtime_json(config: PanelConfig, args: list[str]) -> Any:
    completed = subprocess.run(
        [config.runtime_bin, *args],
        cwd=config.project_root,
        text=True,
        capture_output=True,
        timeout=config.cli_timeout_secs,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"runtime returned non-JSON output: {completed.stdout[:1000]}") from exc


def normalize_context_json(context_json: Any, context: Any) -> str:
    if isinstance(context_json, str) and context_json.strip():
        parsed = json.loads(context_json)
        if not isinstance(parsed, dict):
            raise ValueError("context_json must encode a JSON object")
        return json.dumps(parsed, ensure_ascii=False)
    if isinstance(context, dict):
        return json.dumps(context, ensure_ascii=False)
    return "{}"


def init_history_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table if not exists panel_task_runs(
                id integer primary key autoincrement,
                session_id text not null,
                runtime_addr text not null,
                task text not null,
                context_json text not null,
                status text not null,
                ok integer,
                exit_code integer,
                trace_json text not null default '[]',
                trace_summary text not null default '',
                stderr text not null default '',
                started_at integer not null,
                completed_at integer,
                updated_at integer not null
            )
            """
        )
        conn.execute("create index if not exists panel_task_runs_started_idx on panel_task_runs(started_at desc)")
        conn.execute("create index if not exists panel_task_runs_session_idx on panel_task_runs(session_id)")
        conn.commit()
    finally:
        conn.close()


def history_start_run(
    config: PanelConfig,
    runtime_addr: str,
    session_id: str,
    task: str,
    context_json: str,
    started_at: int | None = None,
) -> int:
    init_history_db(config.history_path)
    now = int(time.time()) if started_at is None else started_at
    conn = sqlite3.connect(config.history_path)
    try:
        cursor = conn.execute(
            """
            insert into panel_task_runs(
                session_id, runtime_addr, task, context_json, status, trace_json,
                started_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, runtime_addr, task, context_json, "running", "[]", now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def history_finish_run(
    config: PanelConfig,
    run_id: int,
    status: str,
    ok: bool,
    exit_code: int | None,
    stderr: str,
    trace_events: list[dict[str, Any]],
    completed_at: int | None = None,
) -> None:
    init_history_db(config.history_path)
    now = int(time.time()) if completed_at is None else completed_at
    trace_json = json.dumps(trace_events, ensure_ascii=False)
    conn = sqlite3.connect(config.history_path)
    try:
        conn.execute(
            """
            update panel_task_runs
            set status = ?, ok = ?, exit_code = ?, trace_json = ?,
                trace_summary = ?, stderr = ?, completed_at = ?, updated_at = ?
            where id = ?
            """,
            (
                status,
                1 if ok else 0,
                exit_code,
                trace_json,
                summarize_trace(trace_events, stderr),
                stderr,
                now,
                now,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def summarize_trace(trace_events: list[dict[str, Any]], stderr: str = "") -> str:
    line_texts = [str(event.get("text") or "") for event in trace_events if event.get("type") == "line" and event.get("text")]
    if line_texts:
        return truncate("\n".join(line_texts[-4:]), 1000)
    reply_events = [event for event in trace_events if event.get("type") == "reply"]
    if reply_events:
        return truncate(json.dumps(reply_events[-1].get("reply"), ensure_ascii=False), 1000)
    error_events = [str(event.get("error") or "") for event in trace_events if event.get("type") == "error"]
    if error_events:
        return truncate(error_events[-1], 1000)
    return truncate(stderr, 1000) if stderr else ""


def memory_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    meta = {}
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        meta = {"raw": row["meta_json"]}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": truncate(row["content"], 800),
        "meta": meta,
        "created_at": row["created_at"],
    }


def history_row_to_dict(row: sqlite3.Row, include_trace: bool) -> dict[str, Any]:
    trace_events = []
    try:
        trace_events = json.loads(row["trace_json"] or "[]")
    except json.JSONDecodeError:
        trace_events = [{"type": "error", "error": "stored trace_json is invalid"}]
    item = {
        "id": row["id"],
        "session_id": row["session_id"],
        "runtime_addr": row["runtime_addr"],
        "task": row["task"] if include_trace else truncate(row["task"], 300),
        "context_json": row["context_json"],
        "status": row["status"],
        "ok": None if row["ok"] is None else bool(row["ok"]),
        "exit_code": row["exit_code"],
        "trace_count": len(trace_events) if isinstance(trace_events, list) else 0,
        "trace_summary": row["trace_summary"],
        "stderr": row["stderr"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }
    if include_trace:
        item["trace"] = trace_events if isinstance(trace_events, list) else []
    return item


def query_value(query: str, key: str) -> str:
    values = parse_qs(query).get(key, [])
    return values[0] if values else ""


def clamp_int(value: str, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, min_value), max_value)


def frontmatter_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def clean_preview(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and line.strip() != "---"]
    return "\n".join(lines[:12])


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"


def resolve_project_root(value: str) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in [Path.cwd().resolve(), *here.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "proto" / "yizutt.proto").exists():
            return parent
    return Path.cwd().resolve()


def resolve_runtime_bin(project_root: Path, value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    if candidate.exists():
        return str(candidate)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
