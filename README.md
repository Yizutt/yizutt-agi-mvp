# Yizutt AGI MVP

Yizutt AGI MVP is a runnable prototype for an evolvable terminal-agent runtime. It combines a Rust gRPC runtime and worker pool with a Python sidecar that handles model calls, working memory, and reusable skill files.

This repository is intentionally small. Its goal is to prove the core loop:

`submit task -> schedule worker -> run Python sidecar -> call model gateway -> write memory -> save skill -> return trace`

## Features

- Rust runtime with local gRPC services for task submission and worker status.
- WorkerPool with basic dynamic scale-up when all healthy workers are busy.
- `clap` based CLI with explicit `run`, `submit`, and `status` commands.
- Python TaskExecutor sidecar launched by Rust workers for real task execution.
- Model gateway adapters for OpenAI, Anthropic, OpenAI-compatible local proxies, and a placeholder local endpoint.
- SQLite FTS5 working memory with extra tokenized search for Chinese and English queries.
- Skill persistence as `SKILL.md` files.
- Real task-memory-skill loop through `python -m yizutt_agi.real_loop`.
- Local Web panel for Runtime status, task submission, recent memory, and skill summaries.

## Repository Layout

- `proto/yizutt.proto` defines `RuntimeService` and `WorkerService`.
- `crates/yizutt-runtime` contains the Rust runtime, worker process, CLI client, and WorkerPool.
- `python/yizutt_agi/executor.py` is the Python sidecar used by Rust workers.
- `python/yizutt_agi/model_gateway.py` provides one model gateway interface.
- `python/yizutt_agi/memory.py` stores cross-session working memory in SQLite FTS5.
- `python/yizutt_agi/skills.py` stores reusable skills as `SKILL.md` files.
- `python/yizutt_agi/panel.py` serves the local Web panel and proxies panel API calls to the runtime CLI.
- `python/yizutt_agi/real_loop.py` runs one direct model-memory-skill loop without starting the Rust runtime.
- `python/yizutt_agi/client.py` calls the Rust runtime CLI from Python.
- `web/panel/index.html` is the browser UI for the local panel.

## Install

Install Rust and Python 3.11 or newer. Then build the Rust runtime:

`cargo build`

Install the Python package in editable mode:

`python -m pip install -e .`

The Rust build uses a vendored `protoc`, so a system `protoc` binary is not required.

## Quick Start

Start the runtime:

`RUST_LOG=info cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4`

Submit a task from another terminal:

`target/debug/yizutt-runtime submit --task "summarize repo architecture"`

Check pool status:

`target/debug/yizutt-runtime status`

Start the local Web panel:

`PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`

Open `http://127.0.0.1:50280` in a browser. The panel lets you edit the Runtime address, inspect workers, submit a task, and view recent memory and skills. Model API keys stay in the server environment and are not exposed to the browser.

Run the Python demo after the runtime is running:

`YIZUTT_RUNTIME_ADDR=http://127.0.0.1:50200 python -m yizutt_agi.demo`

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

The sidecar emits JSON trace events to stdout, calls the model gateway, writes task and answer messages to SQLite working memory, and saves the successful execution path as a skill file. The Rust worker collects those events and returns them in `trace.events`.

Current trace delivery is aggregated in a single gRPC reply. Server-streaming traces are a planned protocol upgrade.

## Memory Search

Working memory stores the original message text plus a tokenized FTS5 index for Chinese and English search. Chinese queries such as `技能`, `运行`, and `运行时` are routed through the tokenized field; English queries continue to work through both original content and token indexes.

Generated memory databases and skill outputs are stored under `.yizutt/`, which is ignored by Git.

## Verified Behavior

The current prototype has been run locally with:

- `cargo build`
- `cargo check`
- `python -m py_compile python/yizutt_agi/*.py`
- `target/debug/yizutt-runtime --help`
- `target/debug/yizutt-runtime run`
- `target/debug/yizutt-runtime submit`
- Python sidecar execution through an OpenAI-compatible local proxy
- Chinese FTS5 memory search for `技能`, `运行`, `运行时`, and `真实模型`

## MVP Boundaries

This is not a production agent runtime yet. Worker sandboxes are local child processes with separate working directories. The WorkerPool performs basic dynamic scale-up but does not yet implement cgroups, containers, remote workers, durable queues, server-streaming traces, long-running tool execution, LoRA training jobs, graph memory, or production-grade backpressure.

## Roadmap

- Add gRPC server-streaming trace APIs.
- Add structured tool execution and cancellation.
- Add stronger worker isolation with containers or OS sandboxing.
- Add health checks that actively probe sidecar execution.
- Add graph memory and skill ranking.
- Add CI for Rust and Python checks.

## License

No license has been selected yet. Add a license before using this as a public open-source project.
