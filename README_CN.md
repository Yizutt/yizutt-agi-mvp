# Yizutt AGI MVP 中文说明

Yizutt AGI MVP 是一个可运行的进化型终端 Agent 运行时原型。它用 Rust 实现本地 gRPC Runtime、Worker 进程管理和 WorkerPool 调度，用 Python sidecar 负责真实任务执行、模型调用、工作记忆和技能文件沉淀。

这个仓库的目标不是一次性做完整 AGI 系统，而是先验证最核心闭环：

`提交任务 -> Runtime 调度 Worker -> Worker 启动 Python sidecar -> 调用模型网关 -> 写入记忆 -> 保存技能 -> 返回 trace`

## 核心能力

- Rust Runtime 提供本地 gRPC 任务提交和 Worker 状态查询。
- WorkerPool 在所有健康 Worker 忙碌时可以做基础动态扩容。
- CLI 已使用 `clap` 重写，明确支持 `run`、`submit`、`status`、`help`。
- Rust Worker 不再返回假结果，而是启动 Python TaskExecutor sidecar 执行真实任务。
- ModelGateway 支持 OpenAI、Anthropic、OpenAI-compatible 本地代理，以及预留本地模型接口。
- SQLite FTS5 工作记忆支持跨会话持久化，并增加中文/英文 tokenized 检索。
- 成功执行路径会保存成 `SKILL.md` 技能文件。
- `python -m yizutt_agi.real_loop` 可以不启动 Rust Runtime，直接跑一次“任务-记录-存技能”闭环。
- 本地 Web 面板支持查看 Runtime 状态、提交任务、查看最近记忆和技能摘要。

## 目录结构

- `proto/yizutt.proto` 定义 `RuntimeService` 和 `WorkerService`。
- `crates/yizutt-runtime` 是 Rust Runtime、Worker 进程、CLI 客户端和 WorkerPool。
- `python/yizutt_agi/executor.py` 是 Rust Worker 启动的 Python sidecar。
- `python/yizutt_agi/model_gateway.py` 是统一模型网关。
- `python/yizutt_agi/memory.py` 是 SQLite FTS5 工作记忆。
- `python/yizutt_agi/skills.py` 负责把技能保存为 `SKILL.md`。
- `python/yizutt_agi/panel.py` 提供本地 Web 面板服务，并把面板 API 代理到 Runtime CLI。
- `python/yizutt_agi/real_loop.py` 负责直接跑一次模型-记忆-技能闭环。
- `python/yizutt_agi/client.py` 是 Python 调 Rust Runtime CLI 的简单客户端。
- `web/panel/index.html` 是本地面板的浏览器页面。

## 安装

需要 Rust 和 Python 3.11 或更新版本。

构建 Rust Runtime：

`cargo build`

安装 Python 包：

`python -m pip install -e .`

Rust 构建使用 vendored `protoc`，不需要系统预装 `protoc`。

## 快速运行

启动 Runtime：

`RUST_LOG=info cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4`

另开一个终端提交任务：

`target/debug/yizutt-runtime submit --task "总结这个项目的架构"`

查看 WorkerPool 状态：

`target/debug/yizutt-runtime status`

启动本地 Web 面板：

`PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`

然后在浏览器打开 `http://127.0.0.1:50280`。面板支持编辑 Runtime 地址、查看 Worker 状态、提交任务、查看最近记忆和技能摘要。模型 API key 只保留在服务端环境变量中，不会暴露给浏览器。

Runtime 启动后运行 Python demo：

`YIZUTT_RUNTIME_ADDR=http://127.0.0.1:50200 python -m yizutt_agi.demo`

## 模型网关

OpenAI：

`export OPENAI_API_KEY=sk-...`

`export YIZUTT_OPENAI_MODEL=gpt-5.4-mini`

`python -m yizutt_agi.real_loop --provider openai --task "用五点总结 Yizutt AGI MVP 架构"`

Anthropic：

`export ANTHROPIC_API_KEY=sk-ant-...`

`export YIZUTT_ANTHROPIC_MODEL=claude-sonnet-4-5-20250929`

`python -m yizutt_agi.real_loop --provider anthropic --task "用五点总结 Yizutt AGI MVP 架构"`

OpenAI-compatible 本地代理：

`export YIZUTT_OPENAI_BASE_URL=http://127.0.0.1:48327/v1`

`export YIZUTT_OPENAI_MODEL=gpt-5.4-mini`

`python -m yizutt_agi.real_loop --provider openai --task "完成一次 Yizutt AGI 任务-记忆-技能闭环"`

当 `YIZUTT_OPENAI_BASE_URL` 不是官方 OpenAI 地址时，Yizutt 会自动走 chat completions。认证优先读取 `OPENAI_API_KEY`，如果没有则回退读取 `PROXY_API_KEY`。密钥只从环境变量读取，不会打印。

## Worker Sidecar

Runtime Worker 执行任务时会启动 Python sidecar：

`python -m yizutt_agi.executor --task-id test --worker-id worker-dev --session-id demo --task "Say hello" --context-json '{"provider":"openai"}'`

sidecar 会向 stdout 输出 JSON trace 事件，调用模型网关，把用户任务、模型回答和 trace 写入 SQLite 工作记忆，并把成功路径保存成技能文件。Rust Worker 会收集这些事件，并在 `trace.events` 中返回。

当前 trace 是一次性聚合返回，还不是 gRPC server-streaming。流式 trace 是下一步协议升级方向。

## 工作记忆与中文检索

工作记忆保存原始消息，同时维护一份 tokenized FTS5 索引。这样英文 token 可以检索，中文查询也可以命中，例如 `技能`、`运行`、`运行时`、`真实模型`。

运行产生的数据库和技能输出位于 `.yizutt/`，该目录已被 Git 忽略。

## 已验证行为

当前原型已经在本地验证：

- `cargo build`
- `cargo check`
- `python -m py_compile python/yizutt_agi/*.py`
- `target/debug/yizutt-runtime --help`
- `target/debug/yizutt-runtime run`
- `target/debug/yizutt-runtime submit`
- 通过 OpenAI-compatible 本地代理执行 Python sidecar 真实模型调用
- 中文 FTS5 检索 `技能`、`运行`、`运行时`、`真实模型`

## MVP 边界

这还不是生产级 Agent Runtime。当前 Worker 沙箱只是本地子进程和独立工作目录；WorkerPool 只有基础动态扩容；还没有 cgroups、容器、远程 Worker、持久队列、gRPC 流式 trace、长任务工具执行、LoRA 训练任务、图记忆和生产级背压。

## 后续路线

- 增加 gRPC server-streaming trace API。
- 增加结构化工具执行和取消机制。
- 用容器或 OS sandbox 加强 Worker 隔离。
- 增加主动探测 sidecar 的健康检查。
- 增加图记忆和技能排序。
- 增加 Rust/Python CI。

## 许可证

当前还没有选择许可证。正式作为开源项目使用前，应补充明确的开源许可证。
