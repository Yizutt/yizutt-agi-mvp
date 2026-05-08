# Nexus AGI MVP

Nexus AGI MVP is a small runnable skeleton for an evolvable terminal agent runtime.

The Rust layer owns the core runtime, local gRPC protocol, worker process isolation, and WorkerPool scheduling. The Python layer owns high-level APIs, model gateway adapters, skill files, and SQLite FTS5 working memory.

## Layout

- `proto/nexus.proto` defines `RuntimeService` and `WorkerService`.
- `crates/nexus-runtime` runs either the runtime server, a worker process, or a small CLI client.
- `python/nexus_agi/executor.py` is the Python sidecar used by Rust workers for real task execution.
- `python/nexus_agi/model_gateway.py` exposes one interface for OpenAI, Anthropic, and a future local model endpoint.
- `python/nexus_agi/skills.py` stores reusable skills as `SKILL.md` files.
- `python/nexus_agi/memory.py` stores cross-session working memory in SQLite with FTS5.
- `python/nexus_agi/client.py` calls the Rust runtime CLI, which in turn talks to the runtime over local gRPC.

## Install

Install Rust and Python 3.11 or newer. Then run:

`cargo build`

For the Python package:

`python -m pip install -e .`

The Rust build uses a vendored `protoc`, so a system `protoc` binary is not required.

## Run

Start the runtime:

`RUST_LOG=info cargo run -p nexus-runtime -- run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4`

Submit a task from another terminal:

`target/debug/nexus-runtime submit --task "summarize repo architecture"`

Check pool status:

`target/debug/nexus-runtime status`

Run the Python demo after the runtime is running:

`python -m nexus_agi.demo`

If you run the runtime on a non-default address, pass it to Python with `NEXUS_RUNTIME_ADDR`, for example:

`NEXUS_RUNTIME_ADDR=http://127.0.0.1:50200 python -m nexus_agi.demo`

## Model gateway

Set `OPENAI_API_KEY` and optionally `NEXUS_OPENAI_MODEL` for OpenAI. Set `ANTHROPIC_API_KEY` and optionally `NEXUS_ANTHROPIC_MODEL` for Anthropic. Set `NEXUS_LOCAL_MODEL_URL` to reserve a local model endpoint.

The real model loop executes one task through the model gateway, writes the task, answer, and trace to SQLite FTS5 working memory, then stores the successful path as a reusable skill file.

For OpenAI:

`export OPENAI_API_KEY=sk-...`

`export NEXUS_OPENAI_MODEL=gpt-5.4-mini`

`python -m nexus_agi.real_loop --provider openai --task "Summarize the Nexus AGI MVP architecture in five bullets."`

For Anthropic:

`export ANTHROPIC_API_KEY=sk-ant-...`

`export NEXUS_ANTHROPIC_MODEL=claude-sonnet-4-5-20250929`

`python -m nexus_agi.real_loop --provider anthropic --task "Summarize the Nexus AGI MVP architecture in five bullets."`

The command prints JSON with `session_id`, selected provider/model, answer, `skill_path`, and memory hit count. API keys are read from the environment and are never printed.

For an OpenAI-compatible local proxy such as CLI Proxy API:

`export NEXUS_OPENAI_BASE_URL=http://127.0.0.1:48327/v1`

`export NEXUS_OPENAI_MODEL=gpt-5.4-mini`

`python -m nexus_agi.real_loop --provider openai --task "Complete one Nexus AGI task-memory-skill loop."`

When `NEXUS_OPENAI_BASE_URL` is not the official OpenAI URL, Nexus uses chat completions automatically. It reads `OPENAI_API_KEY` first and falls back to `PROXY_API_KEY` for local proxy authentication.

## Worker sidecar

Runtime workers execute tasks by spawning the Python sidecar:

`python -m nexus_agi.executor --task-id test --worker-id worker-dev --session-id demo --task "Say hello" --context-json '{"provider":"openai"}'`

The sidecar emits JSON trace events to stdout, calls the model gateway, writes task and answer messages to SQLite working memory, and saves the successful execution path as a skill file. The Rust worker collects those events and returns them in `trace.events`.

## Memory search

Working memory stores the original message text plus a tokenized FTS5 index for Chinese and English search. Chinese queries such as `技能`, `运行`, and `运行时` are routed through the tokenized field; English queries continue to work through both original content and token indexes.

## MVP boundaries

This skeleton intentionally keeps the runtime small. Worker sandboxes are local child processes with separate working directories. The WorkerPool performs basic dynamic scale-up when all healthy workers are busy. It does not yet implement cgroups, containers, remote workers, server-streaming traces, long-running tool execution, LoRA training jobs, graph memory, or production-grade backpressure.
