from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any


TARGET = {
    "name": "yizutt-codex-openclaw-hermes",
    "summary": (
        "Codex-style agent function and execution logic, OpenClaw-style web and command "
        "surface, Hermes-style memory and learning, with governed self-evolution."
    ),
    "principle": "The system can improve itself by turning capability gaps into explicit, testable tasks.",
}

PRODUCT_PILLARS = [
    {
        "name": "codex",
        "focus": "agent function and execution logic",
        "description": "Planner, tool loop, runtime actions, sandbox policy, traces, and task handoff semantics.",
    },
    {
        "name": "openclaw",
        "focus": "web and command surface",
        "description": "Global yizutt command, setup/onboard/gateway flows, and the browser operator workbench.",
    },
    {
        "name": "hermes",
        "focus": "memory and learning",
        "description": "Durable memory, retrieval, skill learning, training buffers, embeddings, and LoRA workflows.",
    },
    {
        "name": "evolution",
        "focus": "self-improvement control loop",
        "description": "Capability gap detection, task generation, verification gates, and upgrade-safe iteration.",
    },
]

CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "codex-agent-loop",
        "pillar": "codex",
        "name": "Agent task loop",
        "status": "implemented",
        "priority": 10,
        "evidence": "Python sidecar calls the model gateway, writes memory, saves skills, and returns trace events.",
        "next_step": "Keep the execution loop stable while adding richer planning and code-review semantics.",
        "acceptance": ["submit returns trace events", "successful runs write memory", "successful runs can save skills"],
        "commands": ["target/debug/yizutt-runtime submit --stream --task \"summarize README\" --context-json '{\"provider\":\"local\"}'"],
    },
    {
        "id": "codex-tool-sandbox",
        "pillar": "codex",
        "name": "Controlled tools and sandbox policy",
        "status": "implemented",
        "priority": 20,
        "evidence": "Tool calls are audited, gated by context flags, and constrained by path, command, and network allowlists.",
        "next_step": "Extend policy profiles for production operator bundles.",
        "acceptance": ["write_file is denied by default", "run_command requires allow_commands and allowlists"],
        "commands": ["python -m py_compile python/yizutt_agi/executor.py"],
    },
    {
        "id": "codex-streaming-trace",
        "pillar": "codex",
        "name": "Streaming trace observation",
        "status": "implemented",
        "priority": 30,
        "evidence": "Runtime supports SubmitStream and the Web panel bridges it to browser SSE.",
        "next_step": "Add trace filtering and export from the workbench.",
        "acceptance": ["submit --stream emits events while the worker runs", "Web task stream updates before completion"],
        "commands": ["target/debug/yizutt-runtime submit --stream --task \"trace smoke\""],
    },
    {
        "id": "codex-planning",
        "pillar": "codex",
        "name": "Planner and subtask orchestration",
        "status": "partial",
        "priority": 40,
        "evidence": "Sidecar emits plan_created events and Runtime can dispatch persisted parallel subtasks.",
        "next_step": "Add priority-aware scheduling, delayed tasks, cancellation, and richer dependency visibility.",
        "acceptance": ["plans include dependencies", "queue status exposes priorities", "cancelled tasks are persisted"],
        "commands": ["target/debug/yizutt-runtime tasks --home .yizutt/runtime --limit 20"],
    },
    {
        "id": "codex-repo-workflows",
        "pillar": "codex",
        "name": "Repository-aware coding workflow",
        "status": "partial",
        "priority": 50,
        "evidence": "Tools can read/write allowed project files and run allowed commands, but there is no dedicated patch/review workflow yet.",
        "next_step": "Add explicit patch proposal, code-review, test-selection, and change-summary trace events.",
        "acceptance": ["file edits are represented as auditable patches", "review mode reports findings first", "test selection is recorded"],
        "commands": ["yizutt evolve --limit 3"],
    },
    {
        "id": "openclaw-global-cli",
        "pillar": "openclaw",
        "name": "Global command surface",
        "status": "implemented",
        "priority": 10,
        "evidence": "The installed yizutt command starts the local Runtime and workbench from any directory.",
        "next_step": "Keep subcommands stable and document compatibility guarantees.",
        "acceptance": ["yizutt starts the local stack", "yizutt start remains a compatibility alias"],
        "commands": ["yizutt --help"],
    },
    {
        "id": "openclaw-setup-onboard",
        "pillar": "openclaw",
        "name": "Guided setup and onboarding",
        "status": "implemented",
        "priority": 20,
        "evidence": "yizutt setup writes config, and yizutt onboard reports paths, gateway, commands, and pillars.",
        "next_step": "Add config migration and schema diagnostics to onboard output.",
        "acceptance": ["setup can run non-interactively", "onboard has JSON output"],
        "commands": ["yizutt setup --yes --dry-run", "yizutt onboard --json"],
    },
    {
        "id": "openclaw-gateway",
        "pillar": "openclaw",
        "name": "Model gateway commands",
        "status": "implemented",
        "priority": 30,
        "evidence": "yizutt gateway reports OpenAI, Anthropic, local, and OpenAI-compatible provider configuration without secrets.",
        "next_step": "Add active provider smoke tests with safe prompt probes.",
        "acceptance": ["gateway status never prints API keys", "provider metadata is machine-readable"],
        "commands": ["yizutt gateway status --json"],
    },
    {
        "id": "openclaw-web-workbench",
        "pillar": "openclaw",
        "name": "Browser operator workbench",
        "status": "implemented",
        "priority": 40,
        "evidence": "Web panel shows runtime health, queue, task stream, history, memory, skills, capabilities, and evolution tasks.",
        "next_step": "Add filtering, export, and release-gate views to the operator workbench.",
        "acceptance": ["workbench exposes runtime status", "workbench exposes capability status"],
        "commands": ["python -m yizutt_agi.panel --help"],
    },
    {
        "id": "openclaw-binary-package",
        "pillar": "openclaw",
        "name": "Portable binary package",
        "status": "implemented",
        "priority": 45,
        "evidence": "scripts/package_binary.sh builds release binaries and produces a tar.gz package with bin/yizutt and bin/yizutt-runtime.",
        "next_step": "Add CI release artifacts for Linux, macOS, Android/Termux, and Windows targets.",
        "acceptance": ["package contains native launchers", "package can run from outside the source tree", "archive has checksum"],
        "commands": ["scripts/package_binary.sh"],
    },
    {
        "id": "openclaw-operator-runbook",
        "pillar": "openclaw",
        "name": "Operator runbook",
        "status": "partial",
        "priority": 50,
        "evidence": "README has startup, sandbox, remote worker, memory, and training commands; upgrade and incident procedures are still thin.",
        "next_step": "Add a production operator runbook for backup, restore, upgrades, incident triage, and release checks.",
        "acceptance": ["backup path is documented", "restore path is documented", "upgrade safety checks are documented"],
        "commands": ["rg -n \"backup|restore|upgrade|operator\" README.md README_CN.md"],
    },
    {
        "id": "hermes-working-memory",
        "pillar": "hermes",
        "name": "Durable working memory",
        "status": "implemented",
        "priority": 10,
        "evidence": "SQLite messages plus FTS5 indexes persist task/user/assistant records across sessions.",
        "next_step": "Add schema migration reporting and backup metadata.",
        "acceptance": ["memory survives process restart", "text search returns recent task context"],
        "commands": ["python -m py_compile python/yizutt_agi/memory.py"],
    },
    {
        "id": "hermes-graph-memory",
        "pillar": "hermes",
        "name": "Graph memory",
        "status": "implemented",
        "priority": 20,
        "evidence": "graph_entities and graph_relations store lightweight facts and one-hop reasoning context.",
        "next_step": "Add richer extraction rules and conflict resolution.",
        "acceptance": ["facts can be searched by graph query", "executor injects relevant graph context"],
        "commands": ["python -m py_compile python/yizutt_agi/memory.py"],
    },
    {
        "id": "hermes-vector-memory",
        "pillar": "hermes",
        "name": "Vector and embedding recall",
        "status": "partial",
        "priority": 30,
        "evidence": "Sparse vectors are always stored; OpenAI-compatible dense embeddings are optional through YIZUTT_EMBEDDING_URL.",
        "next_step": "Add a bundled local embedding provider profile and dimension/index health checks.",
        "acceptance": ["dense embedding status is visible", "fallback search stays available", "dimension mismatch is reported clearly"],
        "commands": ["yizutt onboard --json"],
    },
    {
        "id": "hermes-skill-learning",
        "pillar": "hermes",
        "name": "Skill learning",
        "status": "implemented",
        "priority": 40,
        "evidence": "Successful paths become SKILL.md files with draft, replay-check, and active states.",
        "next_step": "Add skill decay, promotion history, and workflow-level success metrics.",
        "acceptance": ["weak skills stay draft", "active skills are ranked by step content"],
        "commands": ["yizutt skill list"],
    },
    {
        "id": "hermes-training-lora",
        "pillar": "hermes",
        "name": "Training buffer and LoRA preparation",
        "status": "partial",
        "priority": 50,
        "evidence": "Accepted traces can be exported into LoRA-ready JSONL and job manifests; trainer execution is not yet managed.",
        "next_step": "Add managed trainer jobs, adapter artifact lifecycle, and evaluation gates.",
        "acceptance": ["training jobs have durable status", "adapter artifacts are versioned", "promotion requires eval results"],
        "commands": ["python -m yizutt_agi.training prepare-lora --help"],
    },
    {
        "id": "evolution-capability-map",
        "pillar": "evolution",
        "name": "Capability matrix",
        "status": "implemented",
        "priority": 10,
        "evidence": "A shared capability registry feeds CLI and Web output.",
        "next_step": "Keep statuses tied to tests and release gates.",
        "acceptance": ["CLI outputs the matrix", "Web API outputs the same matrix"],
        "commands": ["yizutt capabilities --json"],
    },
    {
        "id": "evolution-gap-planner",
        "pillar": "evolution",
        "name": "Self-evolution task planner",
        "status": "implemented",
        "priority": 20,
        "evidence": "yizutt evolve turns partial/planned capabilities into prioritized implementation tasks.",
        "next_step": "Persist generated tasks and connect them to Runtime execution history.",
        "acceptance": ["evolve output includes objectives", "evolve output includes acceptance checks"],
        "commands": ["yizutt evolve --json"],
    },
    {
        "id": "evolution-safe-automation",
        "pillar": "evolution",
        "name": "Safe autonomous improvement loop",
        "status": "partial",
        "priority": 30,
        "evidence": "The project has tests, CI, trace history, and explicit capability gaps; automatic code-changing loops still need gates.",
        "next_step": "Add opt-in evolve-run mode that creates a task, executes it, runs tests, and records promotion evidence.",
        "acceptance": ["auto mode is opt-in", "tests are mandatory", "failed changes are not promoted"],
        "commands": ["yizutt evolve --write"],
    },
]


def capability_matrix() -> dict[str, Any]:
    capabilities = deepcopy(CAPABILITIES)
    return {
        "ok": True,
        "version": 1,
        "target": deepcopy(TARGET),
        "pillars": deepcopy(PRODUCT_PILLARS),
        "capabilities": capabilities,
        "summary": summarize(capabilities),
    }


def evolution_plan(limit: int = 8) -> dict[str, Any]:
    matrix = capability_matrix()
    gaps = [item for item in matrix["capabilities"] if item["status"] != "implemented"]
    gaps.sort(key=lambda item: (item["priority"], status_rank(item["status"]), item["id"]))
    tasks = []
    for item in gaps[:limit]:
        tasks.append(
            {
                "id": f"evolve-{item['id']}",
                "pillar": item["pillar"],
                "capability": item["name"],
                "status": "queued",
                "objective": item["next_step"],
                "acceptance": list(item.get("acceptance", [])),
                "suggested_commands": list(item.get("commands", [])),
                "source_status": item["status"],
                "priority": item["priority"],
            }
        )
    return {
        "ok": True,
        "generated_at": int(time.time()),
        "target": deepcopy(TARGET),
        "summary": matrix["summary"],
        "tasks": tasks,
    }


def write_evolution_plan(path: Path, plan: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def summarize(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {"implemented": 0, "partial": 0, "planned": 0}
    by_pillar: dict[str, dict[str, int]] = {}
    for item in capabilities:
        status = str(item.get("status") or "planned")
        by_status[status] = by_status.get(status, 0) + 1
        pillar = str(item.get("pillar") or "unknown")
        by_pillar.setdefault(pillar, {"implemented": 0, "partial": 0, "planned": 0, "total": 0})
        by_pillar[pillar][status] = by_pillar[pillar].get(status, 0) + 1
        by_pillar[pillar]["total"] += 1
    total = len(capabilities)
    return {
        "total": total,
        "implemented": by_status.get("implemented", 0),
        "partial": by_status.get("partial", 0),
        "planned": by_status.get("planned", 0),
        "completion_ratio": round(by_status.get("implemented", 0) / total, 3) if total else 0.0,
        "by_status": by_status,
        "by_pillar": by_pillar,
    }


def status_rank(status: str) -> int:
    return {"partial": 0, "planned": 1, "implemented": 2}.get(status, 9)
