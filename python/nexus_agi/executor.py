import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .memory import WorkingMemory, compact_context
from .model_gateway import ModelGateway
from .skills import SkillStore


SYSTEM_PROMPT = (
    "You are the Nexus AGI Python TaskExecutor sidecar. "
    "Execute the task directly, use relevant memory and skills when helpful, "
    "and return a concise final answer."
)


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
    memory_path = Path(os.getenv("NEXUS_MEMORY_PATH", ".nexus/memory/work.sqlite3"))
    skills_root = Path(os.getenv("NEXUS_SKILLS_ROOT", ".nexus/skills"))
    provider = context.get("provider") or os.getenv("NEXUS_EXECUTOR_PROVIDER") or None

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
        answer = gateway.complete(prompt, provider=selected_provider, system=SYSTEM_PROMPT)
        emit("output", answer)

        trace = {
            "task_id": task_id,
            "worker_id": worker_id,
            "provider": selected_provider,
            "model": _model_name(gateway, selected_provider),
            "started_at": started_at,
            "finished_at": int(time.time()),
            "context": context,
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


def build_prompt(task: str, memory_context: str, skill_context: str, context: dict[str, Any]) -> str:
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
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus AGI Python sidecar task executor.")
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
