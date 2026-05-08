import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .memory import WorkingMemory, compact_context
from .model_gateway import ModelGateway
from .skills import SkillStore


SYSTEM_PROMPT = (
    "You are the Yizutt AGI Python TaskExecutor sidecar. "
    "Execute the task directly. Use available tools only when they are needed. "
    "Return either a plain final answer, a JSON object with final_answer, or a "
    "JSON object with tool_calls."
)

ORCHESTRATOR_PROMPT = (
    "You are the Yizutt AGI Leader/Orchestrator. "
    "Break complex work into a small, executable subtask plan. "
    "Return only JSON with this shape: "
    '{"plan":[{"id":"step-1","title":"...","objective":"...","status":"pending"}]}. '
    "Every plan item must include id, title, objective, and status. "
    "Use status=pending. Do not include markdown."
)


TOOL_GUIDE = """
Available tools:
- list_dir: {"path": ".", "max_entries": 100}
- read_file: {"path": "README.md", "max_chars": 12000}
- write_file: {"path": "notes.txt", "content": "..."}; disabled unless context.allow_file_write is true or YIZUTT_EXECUTOR_ALLOW_WRITE=1
- run_command: {"command": ["python", "-V"], "timeout_secs": 10, "max_output_chars": 12000}; disabled unless context.allow_commands is true or YIZUTT_EXECUTOR_ALLOW_COMMANDS=1

When a tool is needed, return only JSON:
{"tool_calls":[{"name":"read_file","arguments":{"path":"README.md"}}]}

When enough information is available, return only JSON:
{"final_answer":"..."}
""".strip()

DEFAULT_DENY_PATH_PARTS = {".git", ".yizutt", "__pycache__", "target"}
ORCHESTRATION_HINTS = {
    "分解",
    "规划",
    "计划",
    "多个任务",
    "多步",
    "复杂",
    "实现",
    "开发",
    "重构",
    "架构",
    "端到端",
    "orchestrate",
    "decompose",
    "plan",
    "multi-step",
    "subtask",
    "workflow",
}


def emit(event_type: str, payload: str = "", **fields: Any) -> None:
    event = {
        "event_type": event_type,
        "payload": payload,
        "timestamp": int(time.time()),
        **fields,
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


def execute_task(task_id: str, worker_id: str, task: str, session_id: str, context_json: str) -> int:
    started_at = int(time.time())
    context = _parse_context(context_json)
    memory_path = Path(os.getenv("YIZUTT_MEMORY_PATH", ".yizutt/memory/work.sqlite3"))
    skills_root = Path(os.getenv("YIZUTT_SKILLS_ROOT", ".yizutt/skills"))
    provider = context.get("provider") or os.getenv("YIZUTT_EXECUTOR_PROVIDER") or None

    emit("accepted", task, task_id=task_id, worker_id=worker_id, session_id=session_id)
    memory = WorkingMemory(memory_path)
    skills = SkillStore(skills_root)
    try:
        memory.append_message(session_id, "user", task, {"kind": "runtime_task", "worker_id": worker_id})
        related_memory = compact_context(memory.search_text(task, limit=5))
        related_skills = skills.skill_context(task)
        emit(
            "context_loaded",
            "",
            memory_items=0 if not related_memory else related_memory.count("\n") + 1,
            skills_chars=len(related_skills),
        )

        prompt = build_prompt(task, related_memory, related_skills, context)
        gateway = ModelGateway()
        selected_provider = gateway.choose(prompt, provider)
        emit("model_selected", selected_provider, model=_model_name(gateway, selected_provider))
        orchestration_plan: list[dict[str, str]] = []
        if should_orchestrate(task, context):
            orchestration_plan = create_task_plan(
                gateway,
                selected_provider,
                task,
                related_memory,
                related_skills,
                context,
            )
            emit(
                "plan_created",
                json.dumps({"plan": orchestration_plan}, ensure_ascii=False),
                plan=orchestration_plan,
            )
            answer, tool_steps = handle_orchestrated_task(
                gateway,
                selected_provider,
                task,
                related_memory,
                related_skills,
                context,
                orchestration_plan,
            )
        else:
            answer, tool_steps = run_tool_loop(
                gateway,
                selected_provider,
                task,
                related_memory,
                related_skills,
                context,
            )
        emit("output", answer)

        trace = {
            "task_id": task_id,
            "worker_id": worker_id,
            "provider": selected_provider,
            "model": _model_name(gateway, selected_provider),
            "started_at": started_at,
            "finished_at": int(time.time()),
            "context": context,
            "tool_steps": tool_steps,
            "orchestration_plan": orchestration_plan,
        }
        memory.append_message(
            session_id,
            "assistant",
            answer,
            {"kind": "runtime_result", "worker_id": worker_id, "provider": selected_provider},
        )
        memory.ingest_trace(session_id, trace)
        skill_path = skills.save_skill(
            name=context.get("skill_name") or _fallback_skill_name(task),
            description=f"Reusable sidecar execution path for: {task[:120]}",
            steps=[
                "Load relevant working memory and reusable skills.",
                "Select the configured model provider.",
                "Create a structured subtask plan when the task requires orchestration.",
                "Call the model gateway with task context.",
                "Persist the answer and trace to working memory.",
                "Save the successful path as a skill file.",
            ],
            source_trace=json.dumps(trace, ensure_ascii=False),
        )
        emit("completed", answer, session_id=session_id, skill_path=str(skill_path))
        return 0
    except Exception as exc:
        emit("error", str(exc), task_id=task_id, worker_id=worker_id, session_id=session_id)
        return 1
    finally:
        memory.close()


def build_prompt(
    task: str,
    memory_context: str,
    skill_context: str,
    context: dict[str, Any],
    tool_observations: list[dict[str, Any]] | None = None,
) -> str:
    observations = json.dumps(tool_observations or [], ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "Task:",
            task,
            "",
            "Runtime context:",
            json.dumps(context, ensure_ascii=False),
            "",
            "Relevant working memory:",
            memory_context or "None.",
            "",
            "Relevant reusable skills:",
            skill_context or "None.",
            "",
            "Tool protocol:",
            TOOL_GUIDE,
            "",
            "Tool observations so far:",
            observations,
        ]
    )


def create_task_plan(
    gateway: ModelGateway,
    provider: str,
    task: str,
    memory_context: str,
    skill_context: str,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    max_subtasks = _int_setting(context, "max_subtasks", "YIZUTT_EXECUTOR_MAX_SUBTASKS", 5)
    max_subtasks = min(max(max_subtasks, 1), 12)
    prompt = build_orchestrator_prompt(task, memory_context, skill_context, context, max_subtasks)
    try:
        raw = gateway.complete(prompt, provider=provider, system=ORCHESTRATOR_PROMPT)
        parsed = _parse_json_object(raw)
        plan = normalize_plan(parsed, task, max_subtasks)
    except Exception as exc:
        emit("plan_fallback", str(exc))
        plan = []
    if not plan:
        plan = fallback_plan(task, max_subtasks)
    return plan


def build_orchestrator_prompt(
    task: str,
    memory_context: str,
    skill_context: str,
    context: dict[str, Any],
    max_subtasks: int,
) -> str:
    return "\n".join(
        [
            "Task to decompose:",
            task,
            "",
            "Constraints:",
            f"- Produce between 2 and {max_subtasks} subtasks unless the work is truly atomic.",
            "- Each subtask must be directly executable by the existing Yizutt worker sidecar.",
            "- Keep objectives concrete and verifiable.",
            "- Use status=pending.",
            "",
            "Runtime context:",
            json.dumps(context, ensure_ascii=False),
            "",
            "Relevant working memory:",
            memory_context or "None.",
            "",
            "Relevant reusable skills:",
            skill_context or "None.",
            "",
            "Return only JSON.",
        ]
    )


def handle_orchestrated_task(
    gateway: ModelGateway,
    provider: str,
    task: str,
    memory_context: str,
    skill_context: str,
    context: dict[str, Any],
    plan: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]]]:
    if not _bool_setting(context, "execute_plan", "YIZUTT_EXECUTOR_EXECUTE_PLAN"):
        return format_plan_answer(task, plan, mode="plan_only"), []

    results: list[dict[str, Any]] = []
    all_steps: list[dict[str, Any]] = []
    for idx, subtask in enumerate(plan):
        subtask["status"] = "running"
        emit("subtask_started", subtask["objective"], subtask=subtask, index=idx)
        sub_context = {
            **context,
            "orchestrate": False,
            "parent_task": task,
            "subtask_id": subtask["id"],
        }
        try:
            sub_answer, sub_steps = run_tool_loop(
                gateway,
                provider,
                subtask["objective"],
                memory_context,
                skill_context,
                sub_context,
            )
            subtask["status"] = "completed"
            result = {
                "id": subtask["id"],
                "title": subtask["title"],
                "status": "completed",
                "output": sub_answer,
            }
            all_steps.extend({"subtask_id": subtask["id"], **step} for step in sub_steps)
            emit("subtask_completed", sub_answer, subtask=subtask, index=idx)
        except Exception as exc:
            subtask["status"] = "failed"
            result = {
                "id": subtask["id"],
                "title": subtask["title"],
                "status": "failed",
                "error": str(exc),
            }
            emit("subtask_failed", str(exc), subtask=subtask, index=idx)
        results.append(result)
        if subtask["status"] == "failed" and not _bool_setting(context, "continue_on_subtask_error", "YIZUTT_EXECUTOR_CONTINUE_ON_SUBTASK_ERROR"):
            break

    return format_plan_answer(task, plan, mode="executed", results=results), all_steps


def format_plan_answer(
    task: str,
    plan: list[dict[str, str]],
    mode: str,
    results: list[dict[str, Any]] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "mode": mode,
        "task": task,
        "plan": plan,
    }
    if results is not None:
        payload["results"] = results
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run_tool_loop(
    gateway: ModelGateway,
    provider: str,
    task: str,
    memory_context: str,
    skill_context: str,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    trace_steps: list[dict[str, Any]] = []
    max_steps = _int_setting(context, "max_tool_steps", "YIZUTT_EXECUTOR_MAX_TOOL_STEPS", 4)
    max_calls_per_step = _int_setting(context, "max_tool_calls_per_step", "YIZUTT_EXECUTOR_MAX_TOOL_CALLS", 4)

    for step_idx in range(max_steps + 1):
        prompt = build_prompt(task, memory_context, skill_context, context, observations)
        raw = gateway.complete(prompt, provider=provider, system=SYSTEM_PROMPT)
        parsed = parse_model_message(raw)

        if parsed.get("kind") == "tool_calls":
            calls = parsed.get("tool_calls", [])
            if step_idx >= max_steps:
                return "Tool loop stopped after reaching max_tool_steps.", trace_steps
            if not calls:
                return raw.strip(), trace_steps

            for call in calls[:max_calls_per_step]:
                name = str(call.get("name") or call.get("tool") or "").strip()
                arguments = call.get("arguments") or call.get("args") or {}
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                emit("tool_call", name, step=step_idx, arguments=arguments)
                result = execute_tool(name, arguments, context)
                emit("tool_result", result["text"], step=step_idx, tool=name, ok=result["ok"])
                observation = {
                    "step": step_idx,
                    "tool": name,
                    "ok": result["ok"],
                    "result": result["text"],
                }
                observations.append(observation)
                trace_steps.append(observation)
            continue

        if parsed.get("kind") == "final":
            return str(parsed.get("final_answer", "")).strip(), trace_steps

        return raw.strip(), trace_steps

    return "Tool loop ended without a final answer.", trace_steps


def parse_model_message(raw: str) -> dict[str, Any]:
    parsed = _parse_json_object(raw)
    if not parsed:
        return {"kind": "plain", "text": raw}

    tool_calls = parsed.get("tool_calls") or parsed.get("tools")
    if isinstance(tool_calls, list):
        normalized = [call for call in tool_calls if isinstance(call, dict)]
        return {"kind": "tool_calls", "tool_calls": normalized}

    for key in ("final_answer", "answer", "output"):
        if isinstance(parsed.get(key), str):
            return {"kind": "final", "final_answer": parsed[key]}

    return {"kind": "plain", "text": raw}


def normalize_plan(parsed: dict[str, Any] | None, task: str, max_subtasks: int) -> list[dict[str, str]]:
    if not isinstance(parsed, dict):
        return []
    raw_plan = parsed.get("plan") or parsed.get("subtasks") or parsed.get("tasks") or []
    if not isinstance(raw_plan, list):
        return []

    plan: list[dict[str, str]] = []
    for idx, item in enumerate(raw_plan[:max_subtasks], start=1):
        if isinstance(item, str):
            title = clean_title(item) or f"Step {idx}"
            objective = item.strip()
        elif isinstance(item, dict):
            title = clean_title(str(item.get("title") or item.get("name") or f"Step {idx}"))
            objective = str(item.get("objective") or item.get("description") or item.get("task") or title).strip()
        else:
            continue
        if not objective:
            continue
        plan.append(
            {
                "id": f"step-{idx}",
                "title": title or f"Step {idx}",
                "objective": objective,
                "status": "pending",
            }
        )
    return ensure_plan_ids(plan, task)


def fallback_plan(task: str, max_subtasks: int) -> list[dict[str, str]]:
    fragments = [
        fragment.strip()
        for fragment in re.split(r"[\n。；;]+|(?:\s+and\s+)", task)
        if fragment.strip()
    ]
    if len(fragments) < 2:
        fragments = [
            f"Clarify the target outcome for: {task}",
            f"Execute the main work for: {task}",
            f"Verify the result and summarize next steps for: {task}",
        ]
    plan = []
    for idx, fragment in enumerate(fragments[:max_subtasks], start=1):
        plan.append(
            {
                "id": f"step-{idx}",
                "title": clean_title(fragment) or f"Step {idx}",
                "objective": fragment,
                "status": "pending",
            }
        )
    return plan


def ensure_plan_ids(plan: list[dict[str, str]], task: str) -> list[dict[str, str]]:
    if not plan:
        return []
    for idx, item in enumerate(plan, start=1):
        item["id"] = f"step-{idx}"
        item["title"] = item.get("title") or f"Step {idx}"
        item["objective"] = item.get("objective") or task
        item["status"] = "pending"
    return plan


def clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip(" -:：")
    if len(text) <= 48:
        return text
    return text[:45].rstrip() + "..."


def execute_tool(name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "list_dir":
            return tool_list_dir(arguments, context)
        if name == "read_file":
            return tool_read_file(arguments, context)
        if name == "write_file":
            return tool_write_file(arguments, context)
        if name == "run_command":
            return tool_run_command(arguments, context)
        return {"ok": False, "text": f"Unknown tool: {name}"}
    except Exception as exc:
        return {"ok": False, "text": f"{type(exc).__name__}: {exc}"}


def tool_list_dir(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_tool_path(arguments.get("path", "."), context)
    max_entries = int(arguments.get("max_entries") or 100)
    if not path.is_dir():
        return {"ok": False, "text": f"not a directory: {path}"}
    entries = []
    denied = set()
    if not _bool_setting(context, "allow_internal_paths", "YIZUTT_EXECUTOR_ALLOW_INTERNAL_PATHS"):
        denied = {str(part) for part in context.get("deny_path_parts", DEFAULT_DENY_PATH_PARTS)}
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        if child.name.startswith(".") or child.name in denied:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
        if len(entries) >= max_entries:
            break
    return {"ok": True, "text": "\n".join(entries)}


def tool_read_file(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_tool_path(arguments.get("path", ""), context)
    max_chars = int(arguments.get("max_chars") or 12000)
    if not path.is_file():
        return {"ok": False, "text": f"not a file: {path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "text": _truncate(text, max_chars)}


def tool_write_file(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not _bool_setting(context, "allow_file_write", "YIZUTT_EXECUTOR_ALLOW_WRITE"):
        return {"ok": False, "text": "write_file disabled; set context.allow_file_write=true or YIZUTT_EXECUTOR_ALLOW_WRITE=1"}
    path = _resolve_tool_path(arguments.get("path", ""), context)
    content = str(arguments.get("content", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "text": f"wrote {len(content)} chars to {path}"}


def tool_run_command(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not _bool_setting(context, "allow_commands", "YIZUTT_EXECUTOR_ALLOW_COMMANDS"):
        return {"ok": False, "text": "run_command disabled; set context.allow_commands=true or YIZUTT_EXECUTOR_ALLOW_COMMANDS=1"}
    command = arguments.get("command")
    if isinstance(command, str):
        command = shlex.split(command)
    if not isinstance(command, list) or not command:
        return {"ok": False, "text": "command must be a non-empty string or list"}
    argv = [str(part) for part in command]
    timeout_secs = int(arguments.get("timeout_secs") or 10)
    max_output_chars = int(arguments.get("max_output_chars") or 12000)
    completed = subprocess.run(
        argv,
        cwd=_project_root(context),
        text=True,
        capture_output=True,
        timeout=timeout_secs,
        check=False,
    )
    text = "\n".join(
        [
            f"exit_code: {completed.returncode}",
            "stdout:",
            completed.stdout,
            "stderr:",
            completed.stderr,
        ]
    )
    return {"ok": completed.returncode == 0, "text": _truncate(text, max_output_chars)}


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _project_root(context: dict[str, Any]) -> Path:
    value = context.get("project_root") or os.getenv("YIZUTT_PROJECT_ROOT") or os.getcwd()
    return Path(str(value)).expanduser().resolve()


def _resolve_tool_path(value: Any, context: dict[str, Any]) -> Path:
    if not value:
        raise ValueError("path is required")
    root = _project_root(context)
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes project root: {value}")
    if not _bool_setting(context, "allow_internal_paths", "YIZUTT_EXECUTOR_ALLOW_INTERNAL_PATHS"):
        denied = {str(part) for part in context.get("deny_path_parts", DEFAULT_DENY_PATH_PARTS)}
        for part in resolved.relative_to(root).parts:
            if part.startswith(".") or part in denied:
                raise ValueError(f"path uses denied internal segment: {part}")
    return resolved


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"


def _bool_setting(context: dict[str, Any], key: str, env_name: str) -> bool:
    if key in context:
        value = context[key]
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
    return os.getenv(env_name, "").lower() in {"1", "true", "yes", "on"}


def should_orchestrate(task: str, context: dict[str, Any]) -> bool:
    if "orchestrate" in context:
        if isinstance(context["orchestrate"], bool):
            return context["orchestrate"]
        return str(context["orchestrate"]).lower() in {"1", "true", "yes", "on"}
    if str(context.get("mode", "")).lower() in {"orchestrate", "orchestration", "plan", "leader"}:
        return True
    if os.getenv("YIZUTT_EXECUTOR_ORCHESTRATE", "").lower() in {"1", "true", "yes", "on"}:
        return True
    lowered = task.lower()
    if any(hint in lowered for hint in ORCHESTRATION_HINTS):
        return True
    return len(task) >= 120 and len(re.split(r"[，,。；;\n]", task)) >= 3


def _int_setting(context: dict[str, Any], key: str, env_name: str, default: int) -> int:
    value = context.get(key, os.getenv(env_name, default))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yizutt AGI Python sidecar task executor.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--context-json", default="{}")
    args = parser.parse_args(argv)
    return execute_task(args.task_id, args.worker_id, args.task, args.session_id, args.context_json)


def _parse_context(context_json: str) -> dict[str, Any]:
    try:
        value = json.loads(context_json or "{}")
    except json.JSONDecodeError:
        return {"raw_context_json": context_json}
    return value if isinstance(value, dict) else {"value": value}


def _model_name(gateway: ModelGateway, provider: str) -> str:
    if provider == "openai":
        return gateway.openai_model
    if provider == "anthropic":
        return gateway.anthropic_model
    if provider == "local":
        return gateway.local_url
    return provider


def _fallback_skill_name(task: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", task.lower())
    if words:
        return "-".join(words[:8])[:80]
    return "runtime-task-skill"


if __name__ == "__main__":
    raise SystemExit(main())
