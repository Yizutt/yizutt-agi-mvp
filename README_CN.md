# Yizutt AGI MVP 中文说明

[![CI](https://github.com/Yizutt/yizutt-agi-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/Yizutt/yizutt-agi-mvp/actions/workflows/ci.yml)

Yizutt AGI MVP 是一个可运行的进化型终端 Agent 运行时原型。它用 Rust 实现本地 gRPC Runtime、Worker 进程管理和 WorkerPool 调度，用 Python sidecar 负责真实任务执行、模型调用、工作记忆和技能文件沉淀。

这个仓库的目标不是一次性做完整 AGI 系统，而是先验证最核心闭环：

`提交任务 -> Runtime 调度 Worker -> Worker 启动 Python sidecar -> 调用模型网关 -> 写入记忆 -> 保存技能 -> 返回 trace`

## 核心能力

- Rust Runtime 提供本地 gRPC 任务提交和 Worker 状态查询。
- gRPC server-streaming trace API 支持在 Worker 运行时实时观察任务事件。
- WorkerPool 在所有健康 Worker 忙碌时可以做基础动态扩容，并支持主动探测 Worker 和 Python sidecar 健康状态。
- CLI 已使用 `clap` 重写，明确支持 `run`、`submit`、`status`、`help`。
- Rust Worker 不再返回假结果，而是启动 Python TaskExecutor sidecar 执行真实任务。
- ModelGateway 支持 OpenAI、Anthropic、OpenAI-compatible 本地代理，以及预留本地模型接口。
- SQLite FTS5 工作记忆支持跨会话持久化，并增加中文/英文 tokenized 检索、SQLite 图记忆和稀疏向量召回。
- 训练数据缓冲区会为成功执行轨迹评分，收集未来微调候选样本，但不会自动启动训练。
- 成功执行路径会保存成带草稿、replay 检查和 active 状态的 `SKILL.md` 技能文件。
- `python -m yizutt_agi.real_loop` 可以不启动 Rust Runtime，直接跑一次“任务-记录-存技能”闭环。
- 本地 Web 面板支持查看 Runtime 状态、提交任务、查看最近记忆和技能摘要，并支持多语言切换。
- 最小 Leader/Orchestrator 规划能力会为复杂任务生成结构化 `plan_created` trace 事件。
- 工具执行带安全审计策略，支持路径白名单、命令白名单，默认拒绝写文件、执行命令和访问内部目录。
- 最小 MCP stdio client 已作为受控 `mcp_call` executor 工具接入。
- 技能包安装器支持 `yizutt skill install <path-or-url>`。

## 目录结构

- `proto/yizutt.proto` 定义 `RuntimeService` 和 `WorkerService`。
- `crates/yizutt-runtime` 是 Rust Runtime、Worker 进程、CLI 客户端和 WorkerPool。
- `python/yizutt_agi/executor.py` 是 Rust Worker 启动的 Python sidecar。
- `python/yizutt_agi/model_gateway.py` 是统一模型网关。
- `python/yizutt_agi/memory.py` 是 SQLite FTS5 工作记忆、实体/关系图谱表和向量记忆表。
- `python/yizutt_agi/skills.py` 负责把技能保存为 `SKILL.md`。
- `python/yizutt_agi/i18n.py` 负责统一解析全局语言短码、环境变量默认值和 CLI 入口后缀。
- `python/yizutt_agi/panel.py` 提供本地 Web 面板服务，并把面板 API 代理到 Runtime CLI。
- `python/yizutt_agi/real_loop.py` 负责直接跑一次模型-记忆-技能闭环。
- `python/yizutt_agi/client.py` 是 Python 调 Rust Runtime CLI 的简单客户端。
- `web/panel/index.html` 是本地面板的浏览器页面。
- `examples/local_mock_model.py` 提供不需要 API key 的确定性本地模型端点，用于端到端 demo。
- `examples/echo_mcp_server.py` 是用于本地工具调用验证的极简 MCP stdio server。
- `examples/skills/echo-skill` 是最小可安装技能包示例。

## 安装

需要 Rust 和 Python 3.11 或更新版本。

构建 Rust Runtime：

`cargo build`

安装 Python 包：

`python -m pip install -e .`

Rust 构建使用 vendored `protoc`，不需要系统预装 `protoc`。

## 快速运行

启动 Runtime：

`RUST_LOG=info cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4 --health-timeout-secs 3`

另开一个终端提交任务：

`target/debug/yizutt-runtime submit --task "总结这个项目的架构"`

任务运行时实时流式查看 trace：

`target/debug/yizutt-runtime submit --stream --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2}'`

查看 WorkerPool 状态：

`target/debug/yizutt-runtime status`

`status` 会主动探测每个 Worker 进程，并验证 Python sidecar 是否能导入 `yizutt_agi.executor`。输出会包含每个 Worker 的 `checked_at` 和 `last_error`。模型或 provider 配置这类任务级错误会作为 `status: "error"` 结果返回，不会把 Worker 误标为 unhealthy。

启动本地 Web 面板：

`PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`

然后在浏览器打开 `http://127.0.0.1:50280`。面板支持编辑 Runtime 地址、查看 Worker 状态、提交任务、查看最近记忆和技能摘要。默认语言是中文-简体，可切换中文-繁体、英语、日语、韩语、阿拉伯语、俄语。模型 API key 只保留在服务端环境变量中，不会暴露给浏览器。

全局语言默认值使用短码。`cnzh` 是默认中文-简体短码。可以用 `--lang cnzh` 启动面板，也可以设置 `YIZUTT_LANG=cnzh`，或使用安装后的入口后缀，例如 `yizutt-panel_cnzh`。支持的入口后缀包括 `_cnzh`、`_twzh`、`_en`、`_ja`、`_ko`、`_ar`、`_ru`。

Runtime 启动后运行 Python demo：

`YIZUTT_RUNTIME_ADDR=http://127.0.0.1:50200 python -m yizutt_agi.demo`

## 端到端本地 Mock Demo

这条流程不需要真实 API key。它会启动一个确定性的本地模型端点，运行 Rust Runtime，提交一个会触发 `read_file` 工具的任务，然后验证 `.yizutt/` 下的工作记忆和技能文件。

终端 1，启动 mock 模型：

`PYTHONPATH=python python examples/local_mock_model.py --port 50990`

终端 2，启动 Runtime，并让 Worker 使用 mock 模型：

`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:50990 target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 2`

终端 3，提交一个使用工具的任务：

`target/debug/yizutt-runtime submit --addr http://127.0.0.1:50200 --session e2e-local --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2,"skill_name":"e2e-local-mock"}'`

检查工作记忆是否能检索到本次结果：

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import json; mem=WorkingMemory(); print(json.dumps(mem.search_text("local mock README", limit=3), ensure_ascii=False, indent=2)); mem.close()'`

检查技能文件是否生成：

`rg --files .yizutt/skills | rg "e2e-local-mock|SKILL.md"`

运行产生的 `.yizutt/` 数据库、Runtime Worker 目录和技能文件都是本地生成物，已被 Git 忽略。

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

sidecar 会向 stdout 输出 JSON trace 事件，调用模型网关，把用户任务、模型回答和 trace 写入 SQLite 工作记忆，并把成功路径保存成技能文件。普通 `submit` 会由 Rust Worker 收集这些事件，并在 `trace.events` 中一次性返回；`submit --stream` 会通过 gRPC server streaming 在事件产生时返回。

最后一个流式事件会带有 `final: true`，包含聚合 trace 和最终任务输出。

## Leader / Orchestrator

复杂任务可以要求 Python sidecar 在执行前先生成结构化子任务计划：

`target/debug/yizutt-runtime submit --task "为本地面板、健康检查和文档更新制定三步实现计划" --context-json '{"provider":"openai","orchestrate":true,"max_subtasks":3}'`

返回 trace 中会包含 `plan_created` 事件。每个子任务都包含 `id`、`title`、`objective`、`status`。默认行为是返回可复用、可持久化的 `plan_only` JSON；如需通过现有工具循环顺序执行子任务，可在 `context_json` 中加入 `"execute_plan": true`。

## 工具安全策略

Python sidecar 支持模型通过结构化 `tool_calls` 调用 `list_dir`、`read_file`、`write_file` 和 `run_command`。每次工具执行前都会先过策略检查。

默认策略是：读操作只能访问项目根目录内的路径；`.git`、`.yizutt`、`__pycache__`、`target` 等隐藏或内部目录禁止访问；写文件默认关闭；命令执行默认关闭。可以用 `context.allowed_paths` 把工具路径进一步收窄到指定项目相对目录。`write_file` 还必须显式设置 `context.allow_file_write=true`。`run_command` 必须同时设置 `context.allow_commands=true` 和命令白名单，例如 `context.allowed_commands=["python"]`。

工具 trace 不再记录原始敏感参数。`tool_call` 记录 `arguments_summary`，`tool_result` 记录 `tool`、`ok`、`allowed`、`reason`、`arguments_summary` 和执行结果。

MCP 默认同样拒绝访问。如需调用 MCP stdio server，需要传入 `context.allow_mcp=true` 并定义 `context.mcp_servers`。策略检查示例：

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; ctx={"allow_mcp":True,"mcp_servers":{"echo":{"command":["python","examples/echo_mcp_server.py"]}}}; result=execute_tool("mcp_call", {"server":"echo","tool":"echo","arguments":{"text":"hello mcp"}}, ctx); print(json.dumps(result, ensure_ascii=False))'`

手动策略检查命令：

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": ".yizutt/memory/work.sqlite3"}, {}), ensure_ascii=False))'`

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": "README.md", "max_chars": 80}, {"allowed_paths":["."]}), ensure_ascii=False))'`

`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("run_command", {"command":["python","-V"]}, {"allow_commands":True,"allowed_commands":["python"]}), ensure_ascii=False))'`

## 工作记忆与中文检索

工作记忆保存原始消息，同时维护一份 tokenized FTS5 索引。这样英文 token 可以检索，中文查询也可以命中，例如 `技能`、`运行`、`运行时`、`真实模型`。

运行产生的数据库和技能输出位于 `.yizutt/`，该目录已被 Git 忽略。

## 图记忆

同一个 SQLite 记忆数据库现在包含 `graph_entities` 和 `graph_relations` 表，用于保存轻量长期事实。`WorkingMemory.append_message()` 会抽取简单跨会话事实，例如用户偏好和项目技术选择；高层代码也可以通过 `add_relation()` 显式写入事实。

可以用 `search_graph(query)` 获取结构化结果，或用 `graph_context(query)` 获取可直接塞进 prompt 的文本，例如 `user -[prefers]-> Rust for runtime design`。executor 和 direct real-loop demo 会在命中相关事实时，把图谱上下文追加到普通 FTS5 记忆上下文后面。

快速检查：

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "I prefer Rust for runtime design."); mem.append_message("s2", "user", "Project Nexus uses SQLite for memory."); print(json.dumps({"rust": mem.search_graph("Rust runtime", 5), "sqlite": mem.graph_context("Nexus SQLite", 5)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## 向量记忆

`memory_vectors` 会为每条消息保存一份轻量稀疏 token 向量。`search_vector(query)` 会对持久化向量做 cosine 相似检索，`vector_context(query)` 会把最佳匹配格式化为可注入 prompt 的上下文。这是一个无额外依赖的本地后端，用于保持 MVP 可移植；后续可以用 FAISS 或 usearch 替换底层存储/检索，而不改变高层 API。

快速检查：

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "Rust runtime workers schedule tasks locally"); mem.append_message("s2", "user", "Python skills store reusable execution steps"); hits=mem.search_vector("local task scheduler in Rust", limit=2); print(json.dumps({"top_session": hits[0]["session_id"], "top_score": round(hits[0]["score"], 3), "context": mem.vector_context("reusable Python skill", 2)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## 训练数据缓冲区

成功执行路径会复制到 SQLite `training_examples` 缓冲区，并写入简单质量分和 accepted 标记。评分会奖励较完整的回答、模型元数据、时间信息、工具调用或编排结构。这一步只收集未来微调候选样本，不会启动 LoRA 或其他训练任务。

快速检查：

`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); trace={"provider":"local","model":"mock","started_at":1,"finished_at":2,"tool_steps":[{"tool":"read_file"}]}; item=mem.record_training_example("s1", "Summarize the runtime architecture", "This answer explains the runtime architecture with enough detail for reuse.", trace); print(json.dumps({"accepted": item["accepted"], "score": item["quality_score"], "stored": len(mem.training_examples(accepted_only=True))}, ensure_ascii=False)); mem.close(); td.cleanup()'`

## 技能质量控制

`SkillStore.save_skill()` 现在使用最小的 draft -> verified -> active 流程。它会先渲染草稿技能，再通过解析生成的 `SKILL.md` 中的 name、description 和编号步骤做一次结构 replay 检查；只有检查通过的技能才会标记为 `active`。过弱技能会保留为 `draft`，并带有 `replay_check: failed`，不会被 `skill_context()` 召回。

为避免技能文件膨胀，同名技能和高度相似技能会合并。已有步骤优先保留，新步骤只追加未重复部分，最终 `SKILL.md` 会在 frontmatter 中记录 `status`、`state_history`、`replay_check`、`updated_at` 和 `similarity_score`。

## 技能包

最小技能包是一个包含 `skill.json` 和 `SKILL.md` 的目录。manifest 包含 `name`、`version`、`description` 和 `skill_file`。执行 `python -m pip install -e .` 后，可以用 `yizutt` 入口从本地路径或 URL 安装技能包。

手动检查：

`PYTHONPATH=python python -m yizutt_agi.skill_market skill install examples/skills/echo-skill --skills-root .yizutt/skill-test`

`PYTHONPATH=python python -m yizutt_agi.skill_market skill list --skills-root .yizutt/skill-test`

## 已验证行为

GitHub Actions 会在 push 到 `main` 和 pull request 时运行核心 CI 检查：`cargo check --workspace --locked`、`cargo build --workspace --locked` 和 `PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`。

当前原型已经在本地验证：

- `cargo build`
- `cargo check`
- `python -m py_compile python/yizutt_agi/*.py`
- `target/debug/yizutt-runtime --help`
- `target/debug/yizutt-runtime run`
- `target/debug/yizutt-runtime submit`
- 通过 OpenAI-compatible 本地代理执行 Python sidecar 真实模型调用
- 本地 Web 面板的状态、任务提交、记忆、技能 API 和多语言切换
- gRPC `submit --stream` 可实时返回 accepted、工具调用、工具结果、训练记录、完成事件和最终输出
- 复杂任务生成 Leader/Orchestrator `plan_created` trace
- 工具循环通过 `read_file` 读取 README 并返回首个标题
- 工具安全策略可拒绝隐藏路径、写文件和命令执行，也可允许白名单命令
- MCP stdio 工具调用默认拒绝和 echo server 授权执行
- 技能 replay 检查、草稿拒绝召回和同名技能合并行为
- 本地技能包安装和列表命令
- 主动健康检查可识别健康 Worker、sidecar 导入失败和任务级错误回复
- 中文 FTS5 检索 `技能`、`运行`、`运行时`、`真实模型`
- SQLite 图记忆抽取和跨会话图谱查询
- 稀疏向量记忆写入、相似检索和 prompt 上下文格式化
- 训练样本评分和 accepted-only 缓冲区查询

## MVP 边界

这还不是生产级 Agent Runtime。当前 Worker 沙箱只是本地子进程和独立工作目录；WorkerPool 只有基础动态扩容；还没有 cgroups、容器、远程 Worker、持久队列、gRPC 流式 trace、长任务工具执行、LoRA 训练任务、基于 embedding 模型的语义向量和生产级背压。

## 后续路线

- 在 Web 面板中增加更完整的流式 trace 消费。
- 增加更完整的工具取消机制和沙箱隔离。
- 用容器或 OS sandbox 加强 Worker 隔离。
- 增强图谱推理和技能排序。
- 增加 Rust/Python CI。

## 许可证

本项目使用 MIT License 开源。详情见 `LICENSE`。
