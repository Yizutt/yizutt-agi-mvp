# Nexus AGI MVP Context

This document records the project context for future contributors and coding agents. It is meant to explain why this prototype exists, what has already been proven, and which parts should be treated as stable versus experimental.

## Project Goal

Nexus AGI is intended to become an evolvable AI teammate framework. The long-term direction includes a runtime kernel, model gateway, memory system, reusable skills, worker orchestration, and eventually self-improvement loops.

This repository is only the MVP runtime skeleton. Its purpose is to prove the smallest useful loop:

`submit task -> schedule worker -> execute Python sidecar -> call model gateway -> write memory -> save skill -> return trace`

The MVP should stay small until the runtime loop is reliable.

## Current Architecture

The Rust layer owns runtime mechanics:

- CLI entrypoint with explicit `run`, `submit`, and `status` commands.
- Local gRPC `RuntimeService` and `WorkerService`.
- WorkerPool scheduling and basic dynamic scale-up.
- Worker child-process lifecycle.
- Worker-side Python sidecar execution and trace collection.

The Python layer owns agent behavior:

- `ModelGateway` for OpenAI, Anthropic, OpenAI-compatible proxy, and local endpoint adapters.
- `WorkingMemory` for SQLite FTS5 session/message persistence.
- `SkillStore` for writing reusable `SKILL.md` files.
- `executor.py` as the sidecar launched by Rust workers.
- `real_loop.py` as a direct task-memory-skill loop without the Rust runtime.

## Runtime Flow

1. A user submits a task through `nexus-runtime submit`.
2. Runtime chooses the least busy healthy worker.
3. Worker calls `python -m nexus_agi.executor`.
4. Python sidecar emits JSON trace events to stdout.
5. Sidecar loads relevant memory and skill context.
6. Sidecar selects a model provider through `ModelGateway`.
7. Sidecar calls the model and receives the final answer.
8. Sidecar writes user task, assistant answer, and trace to SQLite.
9. Sidecar saves the reusable path as a `SKILL.md` file.
10. Rust Worker collects stdout events into `trace.events` and returns one gRPC reply.

Trace delivery is currently aggregated, not streamed.

## Verified Behavior

The prototype has been run locally with:

- `cargo build`
- `cargo check`
- `python -m py_compile python/nexus_agi/*.py`
- `target/debug/nexus-runtime --help`
- `target/debug/nexus-runtime run`
- `target/debug/nexus-runtime status`
- `target/debug/nexus-runtime submit`
- Python sidecar execution through an OpenAI-compatible local proxy at `127.0.0.1:48327`
- Real model call using `gpt-5.4-mini`
- FTS5 memory writes
- Chinese memory queries such as `技能`, `运行`, `运行时`, and `真实模型`
- Skill file creation under `.nexus/skills`

## Important Decisions

The CLI was rewritten with `clap` because the original default path treated unknown commands and `--help` as runtime startup. This caused accidental worker processes and port binding failures.

The Worker execution layer was changed from a fixed string response to a Python sidecar. Rust should remain responsible for process lifecycle and scheduling; Python should remain responsible for agent behavior while the design is still evolving.

The memory layer keeps SQLite FTS5 but adds a tokenized FTS table. The default SQLite tokenizer does not work well for Chinese queries, so `WorkingMemory` stores both original content and generated search tokens.

The current sidecar uses a single final model response. It emits trace events around execution, but does not yet stream model tokens.

## Stable Enough To Reuse

- Rust CLI subcommand structure.
- Local gRPC request/response path.
- WorkerPool basic scheduling and scale-up.
- Python `ModelGateway` provider abstraction.
- `SkillStore` file format and save path.
- SQLite schema as an MVP baseline.
- Chinese tokenized search strategy as a pragmatic MVP fix.

## Experimental Or Incomplete

- Worker sandboxing is only a child process with a separate working directory.
- Trace events are aggregated in one reply, not server-streamed.
- Worker health only reports process availability, not full sidecar/model readiness.
- There is no durable queue.
- There is no cancellation API.
- There is no structured tool runner yet.
- There is no graph memory.
- There is no LoRA or fine-tuning pipeline.
- There is no CI.
- There is no license yet.

## Recommended Next Steps

1. Add a license before promoting the repository as an open-source project.
2. Add CI for `cargo check`, `cargo build`, and Python `py_compile`.
3. Add gRPC server-streaming APIs for trace events.
4. Add structured tool execution with timeout, cancellation, and typed errors.
5. Add active Worker health checks that call the sidecar in a cheap probe mode.
6. Add a durable queue before supporting long-running work.
7. Improve memory ranking and add skill retrieval tests.
8. Add integration tests for the full Rust-to-Python sidecar path.

## Local Proxy Notes

The tested environment used an OpenAI-compatible proxy:

`NEXUS_OPENAI_BASE_URL=http://127.0.0.1:48327/v1`

`NEXUS_OPENAI_MODEL=gpt-5.4-mini`

For custom OpenAI-compatible base URLs, `ModelGateway` uses chat completions automatically. It reads `OPENAI_API_KEY` first and falls back to `PROXY_API_KEY` for local proxy authentication.

Do not commit API keys, `.nexus/`, `target/`, `__pycache__/`, or `*.egg-info/`.
