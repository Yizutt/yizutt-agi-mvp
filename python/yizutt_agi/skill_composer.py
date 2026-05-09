import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from .skills import SkillStore


def compose_workflow(
    goal: str,
    skills_root: str | Path = ".yizutt/skills",
    workflows_root: str | Path = ".yizutt/workflows",
    max_skills: int = 5,
) -> dict[str, Any]:
    store = SkillStore(skills_root)
    chain = discover_skill_chain(goal, store, max_skills=max_skills)
    if not chain:
        raise ValueError("no matching skills found")
    workflow_name = safe_workflow_name(goal)
    workflow_dir = Path(workflows_root) / workflow_name
    workflow_dir.mkdir(parents=True, exist_ok=True)
    path = workflow_dir / "WORKFLOW.md"
    text = render_workflow(goal, workflow_name, chain)
    path.write_text(text, encoding="utf-8")
    return {"name": workflow_name, "path": str(path), "skills": chain}


def discover_skill_chain(goal: str, store: SkillStore, max_skills: int = 5) -> list[dict[str, Any]]:
    chain = []
    for item in store.search_skills(goal, limit=max_skills):
        chain.append({
            "name": item["name"],
            "description": item.get("description", ""),
            "path": item["path"],
            "score": item["score"],
            "matched_terms": item.get("matched_terms", []),
            "step_count": item.get("step_count", 0),
        })
    return chain


def render_workflow(goal: str, workflow_name: str, chain: list[dict[str, Any]]) -> str:
    now = int(time.time())
    lines = [
        "---",
        f"name: {workflow_name}",
        f"goal: {single_line(goal)}",
        f"created_at: {now}",
        "status: draft",
        "---",
        "",
        "目标:",
        goal,
        "",
        "技能链:",
    ]
    for idx, skill in enumerate(chain, start=1):
        lines.extend(
            [
                f"{idx}. {skill['name']}",
                f"   - 描述: {skill['description']}",
                f"   - 匹配分: {skill['score']}",
                f"   - 命中词: {', '.join(skill.get('matched_terms', []))}",
                f"   - 步骤数: {skill.get('step_count', 0)}",
                f"   - 路径: {skill['path']}",
            ]
        )
    lines.extend(
        [
            "",
            "执行模板:",
            "1. 加载上述技能的触发条件和执行步骤。",
            "2. 按技能链顺序执行；每步输出作为下一步输入。",
            "3. 如果某个技能不适用，记录原因并跳过。",
            "4. 汇总最终结果、trace、记忆更新和可复用改进点。",
        ]
    )
    return "\n".join(lines) + "\n"


def safe_workflow_name(goal: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff-]+", "-", goal.strip().lower()).strip("-")
    if not cleaned:
        cleaned = "workflow"
    return cleaned[:80]


def single_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose a workflow from installed Yizutt skills.")
    parser.add_argument("compose", nargs="?", help="Use the literal subcommand: compose")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--skills-root", default=".yizutt/skills")
    parser.add_argument("--workflows-root", default=".yizutt/workflows")
    parser.add_argument("--max-skills", type=int, default=5)
    args = parser.parse_args(argv)
    if args.compose != "compose":
        parser.error("expected subcommand: compose")
    result = compose_workflow(args.goal, args.skills_root, args.workflows_root, args.max_skills)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
