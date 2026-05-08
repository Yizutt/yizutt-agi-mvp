import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from .memory import WorkingMemory, compact_context
from .model_gateway import ModelGateway
from .skills import SkillStore


SYSTEM_PROMPT = (
    "You are Yizutt AGI running a minimal task-memory-skill loop. "
    "Complete the user task directly, then return strict JSON with these keys: "
    "answer, reusable_steps, skill_name, skill_description. "
    "reusable_steps must be a list of concrete steps that can be reused later."
)


def build_prompt(task: str, memory_context: str, skill_context: str) -> str:
    return "\n".join(
        [
            "Task:",
            task,
            "",
            "Relevant working memory:",
            memory_context or "None.",
            "",
            "Relevant reusable skills:",
            skill_context or "None.",
            "",
            "Return only JSON. Do not wrap it in Markdown.",
        ]
    )


def parse_model_result(raw: str, task: str) -> dict[str, Any]:
    parsed = _parse_json_object(raw)
    if parsed is None:
        return {
            "answer": raw.strip(),
            "reusable_steps": [
                "Clarify the task goal and constraints.",
                "Call the selected model provider with relevant context.",
                "Record the task input, model output, and execution trace.",
                "Save the successful path as a reusable skill.",
            ],
            "skill_name": _fallback_skill_name(task),
            "skill_description": f"Reusable path for task: {task[:120]}",
        }

    answer = str(parsed.get("answer") or raw).strip()
    steps = parsed.get("reusable_steps")
    if not isinstance(steps, list):
        steps = parsed.get("steps")
    if not isinstance(steps, list):
        steps = ["Call selected model provider.", "Record result in working memory.", "Persist reusable execution path."]
    normalized_steps = [str(step).strip() for step in steps if str(step).strip()]
    if not normalized_steps:
        normalized_steps = ["Call selected model provider.", "Record result in working memory.", "Persist reusable execution path."]

    return {
        "answer": answer,
        "reusable_steps": normalized_steps[:12],
        "skill_name": str(parsed.get("skill_name") or _fallback_skill_name(task)).strip(),
        "skill_description": str(parsed.get("skill_description") or f"Reusable path for task: {task[:120]}").strip(),
    }


def run_real_loop(
    task: str,
    provider: str | None = None,
    skill_name: str | None = None,
    memory_path: str | Path = ".yizutt/memory/work.sqlite3",
    skills_root: str | Path = ".yizutt/skills",
) -> dict[str, Any]:
    gateway = ModelGateway()
    selected_provider = gateway.choose(task, provider)
    selected_model = _model_name(gateway, selected_provider)
    memory = WorkingMemory(memory_path)
    skills = SkillStore(skills_root)
    session_id = memory.start_session(task[:80])
    started_at = int(time.time())

    try:
        memory.append_message(
            session_id,
            "user",
            task,
            {"kind": "task", "provider": selected_provider, "model": selected_model},
        )
        related_memory = compact_context(memory.search(_safe_fts_query(task), limit=5))
        related_graph = memory.graph_context(task, limit=5)
        if related_graph:
            related_memory = "\n".join(part for part in [related_memory, "Graph memory:", related_graph] if part)
        related_skills = skills.skill_context(task)
        prompt = build_prompt(task, related_memory, related_skills)
        raw = gateway.complete(prompt, provider=selected_provider, system=SYSTEM_PROMPT)
        result = parse_model_result(raw, task)
        final_skill_name = skill_name or result["skill_name"] or _fallback_skill_name(task)
        trace = {
            "provider": selected_provider,
            "model": selected_model,
            "session_id": session_id,
            "started_at": started_at,
            "finished_at": int(time.time()),
            "prompt_chars": len(prompt),
            "raw_response_chars": len(raw),
        }

        memory.append_message(
            session_id,
            "assistant",
            result["answer"],
            {"kind": "model_result", "provider": selected_provider, "model": selected_model},
        )
        memory.ingest_trace(session_id, trace)
        skill_path = _save_skill_with_fallback(
            skills,
            final_skill_name,
            result["skill_description"],
            result["reusable_steps"],
            json.dumps(trace, ensure_ascii=False),
            task,
        )
        hits = memory.search(_safe_fts_query(task), limit=10)

        return {
            "ok": True,
            "session_id": session_id,
            "provider": selected_provider,
            "model": selected_model,
            "answer": result["answer"],
            "skill_path": str(skill_path),
            "memory_path": str(Path(memory_path)),
            "memory_hits": len(hits),
            "trace": trace,
        }
    finally:
        memory.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one real Yizutt AGI task-memory-skill loop.")
    parser.add_argument("--task", required=True, help="Task to execute with a real model provider.")
    parser.add_argument("--provider", choices=["auto", "openai", "anthropic", "local"], default="auto")
    parser.add_argument("--skill-name", default="", help="Optional skill name override.")
    parser.add_argument("--memory-path", default=".yizutt/memory/work.sqlite3")
    parser.add_argument("--skills-root", default=".yizutt/skills")
    args = parser.parse_args(argv)

    try:
        result = run_real_loop(
            task=args.task,
            provider=None if args.provider == "auto" else args.provider,
            skill_name=args.skill_name or None,
            memory_path=args.memory_path,
            skills_root=args.skills_root,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
        base = "-".join(words[:8])
    else:
        base = "task"
    digest = hashlib.sha1(task.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"[:80]


def _safe_fts_query(text: str) -> str:
    terms = re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text)
    if not terms:
        return '"task"'
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _save_skill_with_fallback(
    skills: SkillStore,
    name: str,
    description: str,
    steps: list[str],
    source_trace: str,
    task: str,
) -> Path:
    try:
        return skills.save_skill(name, description, steps, source_trace)
    except ValueError:
        return skills.save_skill(_fallback_skill_name(task), description, steps, source_trace)


if __name__ == "__main__":
    raise SystemExit(main())
