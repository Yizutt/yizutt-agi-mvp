# Yizutt AGI MVP

[![CI](https://github.com/Yizutt/yizutt-agi-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/Yizutt/yizutt-agi-mvp/actions/workflows/ci.yml)

Yizutt AGI MVP is a runnable prototype for an evolvable terminal-agent runtime. It combines a Rust gRPC runtime and worker pool with a Python sidecar that handles model calls, working memory, and reusable skill files.

This repository is intentionally small. Its goal is to prove the core loop:

`submit task -> schedule worker -> run Python sidecar -> call model gateway -> write memory -> save skill -> return trace`

## Features

- Rust runtime with local gRPC services for task submission and worker status.
- Server-streaming trace API for observing task events while a worker is running.
- WorkerPool with basic dynamic scale-up and active worker/sidecar health checks.
- `clap` based CLI with explicit `run`, `submit`, and `status` commands.
- Python TaskExecutor sidecar launched by Rust workers for real task execution.
- Model gateway adapters for OpenAI, Anthropic, OpenAI-compatible local proxies, and a placeholder local endpoint.
- SQLite FTS5 working memory with tokenized search, SQLite graph memory, and sparse vector recall.
- Training data buffer that scores successful traces for future fine-tuning datasets without starting training jobs.
- Skill persistence as `SKILL.md` files with draft, replay-check, and active states.
- Real task-memory-skill loop through `python -m yizutt_agi.real_loop`.
- Local Web panel for Runtime status, task submission, recent memory, skill summaries, and language switching.
- Minimal Leader/Orchestrator planning that emits structured `plan_created` trace events for complex tasks.
- Audited tool policy with path allowlists, command allowlists, and default denial for writes, commands, and internal directories.
- Minimal MCP stdio client exposed as a gated `mcp_call` executor tool.
- Skill package installer with `yizutt skill install <path-or-url>`.
- Team memory bundle export/import for sharing memory and skills across agent workspaces.

## Repository Layout

- `proto/yizutt.proto` defines `RuntimeService` and `WorkerService`.
- `crates/yizutt-runtime` contains the Rust runtime, worker process, CLI client, and WorkerPool.
- `python/yizutt_agi/executor.py` is the Python sidecar used by Rust workers.
- `python/yizutt_agi/model_gateway.py` provides one model gateway interface.
- `python/yizutt_agi/memory.py` stores cross-session working memory in SQLite FTS5 plus graph and vector memory tables.
- `python/yizutt_agi/skills.py` stores reusable skills as `SKILL.md` files.
- `python/yizutt_agi/i18n.py` resolves global language short codes, environment defaults, and CLI entrypoint suffixes.
- `python/yizutt_agi/panel.py` serves the local Web panel and proxies panel API calls to the runtime CLI.
- `python/yizutt_agi/real_loop.py` runs one direct model-memory-skill loop without starting the Rust runtime.
- `python/yizutt_agi/client.py` calls the Rust runtime CLI from Python.
- `web/panel/index.html` is the browser UI for the local panel.
- `examples/local_mock_model.py` serves a deterministic local model endpoint for no-key end-to-end demos.
- `examples/echo_mcp_server.py` is a tiny MCP stdio server for local tool-call validation.
- `examples/skills/echo-skill` is a minimal installable skill package.

## Install

Install Rust and Python 3.11 or newer. Then build the Rust runtime:

`cargo build`

Install the Python package in editable mode:

`python -m pip install -e .`

The Rust build uses a vendored `protoc`, so a system `protoc` binary is not required.

## Quick Start

Start the runtime:

`RUST_LOG=info cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4 --health-timeout-secs 3`

Submit a task from another terminal:

`target/debug/yizutt-runtime submit --task "summarize repo architecture"`

Stream trace events while a task is running:

`target/debug/yizutt-runtime submit --stream --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2}'`

Check pool status:

`target/debug/yizutt-runtime status`

`status` actively probes each worker process and verifies that the Python sidecar can import `yizutt_agi.executor`. The output includes `checked_at` and `last_error` for each worker. Task-level model or provider errors are returned as `status: "error"` replies and do not mark the worker unhealthy.

Start the local Web panel:

`PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`

Open `http://127.0.0.1:50280` in a browser. The panel lets you edit the Runtime address, inspect workers, submit a task, and view recent memory and skills. The default UI language is Simplified Chinese, with Traditional Chinese, English, Japanese, Korean, Arabic, and Russian available from the language selector. Model API keys stay in the server environment and are not exposed to the browser.

Global language defaults use short codes. `cnzh` is the default Simplified Chinese code. You can start the panel with `--lang cnzh`, set `YIZUTT_LANG=cnzh`, or use an installed entrypoint suffix such as `yizutt-panel_cnzh`. Supported entrypoint suffixes are `_cnzh`, `_twzh`, `_en`, `_ja`, `_ko`, `_ar`, and `_ru`.

Run the Python demo after the runtime is running:

`YIZUTT_RUNTIME_ADDR=http://127.0.0.1:50200 python -m yizutt_agi.demo`

## End-to-End Local Mock Demo

This flow needs no real API key. It starts a deterministic local model endpoint, runs the Rust Runtime, submits a task that triggers the `read_file` tool, then verifies memory and skill outputs under `.yizutt/`.

Terminal 1, start the mock model:

`PYTHONPATH=python python examples/local_mock_model.py --port 50990`

Terminal 2, start the runtime and point workers at the mock model:

`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:50990 target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 2`

Terminal 3, submit a tool-using task:

`target/debug/yizutt-runtime submit --addr http://127.0.0.1:50200 --session e2e-local --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2,"skill_name":"e2e-local-mock"}'`

Check that working memory can find the session result:

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import json; mem=WorkingMemory(); print(json.dumps(mem.search_text("local mock README", limit=3), ensure_ascii=False, indent=2)); mem.close()'`

Check that a reusable skill file was generated:

`rg --files .yizutt/skills | rg "e2e-local-mock|SKILL.md"`

Generated `.yizutt/` memory databases, runtime worker folders, and skill files are local artifacts and are ignored by Git.

## Model Gateway

OpenAI:

`export OPENAI_API_KEY=sk-...`

`export YIZUTT_OPENAI_MODEL=gpt-5.4-mini`

`python -m yizutt_agi.real_loop --provider openai --task "Summarize the Yizutt AGI MVP architecture in five bullets."`

Anthropic:

`export ANTHROPIC_API_KEY=sk-ant-...`

`export YIZUTT_ANTHROPIC_MODEL=claude-sonnet-4-5-20250929`

`python -m yizutt_agi.real_loop --provider anthropic --task "Summarize the Yizutt AGI MVP architecture in five bullets."`

OpenAI-compatible local proxy:

`export YIZUTT_OPENAI_BASE_URL=http://127.0.0.1:48327/v1`

`export YIZUTT_OPENAI_MODEL=gpt-5.4-mini`

`python -m yizutt_agi.real_loop --provider openai --task "Complete one Yizutt AGI task-memory-skill loop."`

When `YIZUTT_OPENAI_BASE_URL` is not the official OpenAI URL, Yizutt uses chat completions automatically. It reads `OPENAI_API_KEY` first and falls back to `PROXY_API_KEY` for local proxy authentication. API keys are read from the environment and are never printed.

## Worker Sidecar

Runtime workers execute tasks by spawning the Python sidecar:

`python -m yizutt_agi.executor --task-id test --worker-id worker-dev --session-id demo --task "Say hello" --context-json '{"provider":"openai"}'`

The sidecar emits JSON trace events to stdout, calls the model gateway, writes task and answer messages to SQLite working memory, and saves the successful execution path as a skill file. The Rust worker collects those events and returns them in `trace.events` for normal `submit`; `submit --stream` returns the same events through gRPC server streaming as they arrive.

The final stream item has `final: true`, includes the aggregated trace, and carries the final task output.

## Leader / Orchestrator

Complex tasks can ask the Python sidecar to create a structured subtask plan before execution:

`target/debug/yizutt-runtime submit --task "Plan a three-step implementation for a local dashboard, health check, and docs update" --context-json '{"provider":"openai","orchestrate":true,"max_subtasks":3}'`

The returned trace includes a `plan_created` event. Each plan item includes `id`, `title`, `objective`, and `status`. By default the sidecar returns a reusable `plan_only` JSON result. To execute subtasks sequentially through the existing tool loop, pass `"execute_plan": true` in `context_json`.

## Tool Security

The Python sidecar can run `list_dir`, `read_file`, `write_file`, and `run_command` when a model returns structured `tool_calls`. Tool execution is policy gated before any file or process action.

By default, reads are confined to the project root, hidden/internal paths such as `.git`, `.yizutt`, `__pycache__`, and `target` are denied, file writes are denied, and command execution is denied. `context.allowed_paths` narrows readable or writable paths to specific project-relative directories. `write_file` additionally requires `context.allow_file_write=true`. `run_command` requires both `context.allow_commands=true` and an executable whitelist such as `context.allowed_commands=["python"]`.

Tool trace events avoid raw sensitive arguments. `tool_call` records `arguments_summary`, and `tool_result` records `tool`, `ok`, `allowed`, `reason`, `arguments_summary`, and the result text.

MCP access is also denied by default. To call an MCP stdio server, pass `context.allow_mcp=true` and define `context.mcp_servers`. Example policy check:

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; ctx={"allow_mcp":True,"mcp_servers":{"echo":{"command":["python","examples/echo_mcp_server.py"]}}}; result=execute_tool("mcp_call", {"server":"echo","tool":"echo","arguments":{"text":"hello mcp"}}, ctx); print(json.dumps(result, ensure_ascii=False))'`

Manual policy checks:

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": ".yizutt/memory/work.sqlite3"}, {}), ensure_ascii=False))'`

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": "README.md", "max_chars": 80}, {"allowed_paths":["."]}), ensure_ascii=False))'`

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("run_command", {"command":["python","-V"]}, {"allow_commands":True,"allowed_commands":["python"]}), ensure_ascii=False))'`

## Memory Search

Working memory stores the original message text plus a tokenized FTS5 index for Chinese and English search. Chinese queries such as `技能`, `运行`, and `运行时` are routed through the tokenized field; English queries continue to work through both original content and token indexes.

Generated memory databases and skill outputs are stored under `.yizutt/`, which is ignored by Git.

## Graph Memory

The same SQLite memory database now includes `graph_entities` and `graph_relations` tables for lightweight long-term facts. `WorkingMemory.append_message()` extracts simple cross-session facts such as user preferences and project technology choices, while `add_relation()` can store explicit facts from higher-level code.

Use `search_graph(query)` for structured results or `graph_context(query)` for prompt-ready lines such as `user -[prefers]-> Rust for runtime design`. The executor and direct real-loop demo append graph context to the normal FTS5 memory context when relevant facts are found.

Quick check:

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "I prefer Rust for runtime design."); mem.append_message("s2", "user", "Project Nexus uses SQLite for memory."); print(json.dumps({"rust": mem.search_graph("Rust runtime", 5), "sqlite": mem.graph_context("Nexus SQLite", 5)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## Vector Memory

`memory_vectors` stores a lightweight sparse token vector for every message. `search_vector(query)` performs cosine similarity over persisted vectors, and `vector_context(query)` formats the best matches for prompt injection. This is a dependency-free local backend intended to keep the MVP portable; FAISS or usearch can replace the storage/search backend later without changing the high-level API.

Quick check:

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "Rust runtime workers schedule tasks locally"); mem.append_message("s2", "user", "Python skills store reusable execution steps"); hits=mem.search_vector("local task scheduler in Rust", limit=2); print(json.dumps({"top_session": hits[0]["session_id"], "top_score": round(hits[0]["score"], 3), "context": mem.vector_context("reusable Python skill", 2)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## Training Buffer

Successful execution paths are copied into a SQLite `training_examples` buffer with a simple quality score and acceptance flag. The score rewards substantive answers, model metadata, timing, and recorded tool or orchestration structure. This only collects future fine-tuning candidates; it does not start LoRA or any other training job.

Quick check:

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); trace={"provider":"local","model":"mock","started_at":1,"finished_at":2,"tool_steps":[{"tool":"read_file"}]}; item=mem.record_training_example("s1", "Summarize the runtime architecture", "This answer explains the runtime architecture with enough detail for reuse.", trace); print(json.dumps({"accepted": item["accepted"], "score": item["quality_score"], "stored": len(mem.training_examples(accepted_only=True))}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## Skill Quality Control

`SkillStore.save_skill()` now uses a minimal draft -> verified -> active flow. It renders a draft skill, replays the generated `SKILL.md` structure by parsing name, description, and numbered steps, and only marks the skill `active` when the replay check passes. Weak skills remain `draft` with `replay_check: failed` and are not returned by `skill_context()`.

To prevent skill file growth, same-name skills and highly similar skills are merged. Existing steps are kept first, new unique steps are appended, and the final `SKILL.md` records `status`, `state_history`, `replay_check`, `updated_at`, and `similarity_score` in frontmatter.

## Skill Packages

A minimal skill package is a directory containing `skill.json` and `SKILL.md`. The package manifest includes `name`, `version`, `description`, and `skill_file`. After `python -m pip install -e .`, the `yizutt` entrypoint can install packages from a local path or a URL.

Manual check:

`PYTHONPATH=python python -m yizutt_agi.skill_market skill install examples/skills/echo-skill --skills-root .yizutt/skill-test`

`PYTHONPATH=python python -m yizutt_agi.skill_market skill list --skills-root .yizutt/skill-test`

## Team Sync

`team_sync.py` exports a portable zip bundle containing memory messages and skill packages. Another Yizutt workspace can import the bundle to merge team memory and skills. Imported messages rebuild FTS, graph, and vector indexes through the normal `WorkingMemory.append_message()` path.

Manual check:

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; from yizutt_agi.skills import SkillStore; mem=WorkingMemory(".yizutt/team-test/source.sqlite3"); mem.append_message("team-s1", "user", "I prefer Rust for team runtime work."); mem.append_message("team-s1", "assistant", "Noted team runtime preference."); mem.close(); SkillStore(".yizutt/team-test/source-skills").save_skill("team-echo", "Share a team echo skill", ["Read phrase", "Return phrase unchanged"], "{}")'`

`PYTHONPATH=python python -m yizutt_agi.team_sync export --bundle .yizutt/team-test/team.zip --memory-path .yizutt/team-test/source.sqlite3 --skills-root .yizutt/team-test/source-skills`

`PYTHONPATH=python python -m yizutt_agi.team_sync import --bundle .yizutt/team-test/team.zip --memory-path .yizutt/team-test/dest.sqlite3 --skills-root .yizutt/team-test/dest-skills`

## Verified Behavior

GitHub Actions runs the core CI checks on push to `main` and on pull requests: `cargo check --workspace --locked`, `cargo build --workspace --locked`, and `PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`.

The current prototype has been run locally with:

- `cargo build`
- `cargo check`
- `python -m py_compile python/yizutt_agi/*.py`
- `target/debug/yizutt-runtime --help`
- `target/debug/yizutt-runtime run`
- `target/debug/yizutt-runtime submit`
- Python sidecar execution through an OpenAI-compatible local proxy
- Local Web panel status, task submission, memory, skill APIs, and language switching
- gRPC `submit --stream` trace events for accepted, tool calls, tool results, training records, completion, and final output
- Leader/Orchestrator `plan_created` trace generation for a complex task
- Tool loop execution with `read_file` returning the first README heading
- Tool policy denial for hidden paths, writes, and commands, plus allowlisted command execution
- MCP stdio tool call denial and allowlisted echo-server execution
- Skill replay checks, draft rejection, and same-name skill merge behavior
- Local skill package install and list commands
- Team bundle export/import for shared memory and skills
- Active health checks for healthy workers, sidecar import failures, and task-level error replies
- Chinese FTS5 memory search for `技能`, `运行`, `运行时`, and `真实模型`
- SQLite graph memory extraction and cross-session graph lookup
- Sparse vector memory write, search, and prompt context formatting
- Training example scoring and accepted-only buffer lookup

## MVP Boundaries

This is not a production agent runtime yet. Worker sandboxes are local child processes with separate working directories. The WorkerPool performs basic dynamic scale-up but does not yet implement cgroups, containers, remote workers, durable queues, server-streaming traces, long-running tool execution, LoRA training jobs, embedding-model semantic vectors, or production-grade backpressure.

## Roadmap

- Add richer stream consumers in the Web panel.
- Add richer tool execution cancellation and sandboxing.
- Add stronger worker isolation with containers or OS sandboxing.
- Add richer graph reasoning and skill ranking.
- Add CI for Rust and Python checks.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
