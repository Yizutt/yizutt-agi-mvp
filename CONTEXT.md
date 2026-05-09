# CONTEXT.md — Yizutt AGI MVP 项目状态

本文档供 AI 助手快速理解项目结构、约束和当前任务。执行任务时以第六节为当前目标。

## 一、项目简介

Yizutt AGI 是一个自进化、多 Agent 协作的 AI 队友框架，采用 Rust 核心运行时 + Python 技能层的混合架构。目标是实现本地优先、模型无关、越用越聪明的个人 AI 助手。

## 二、已完成的核心特性

- **项目更名**：对外项目名已从旧名称迁移为 Yizutt AGI。
- **Rust Runtime & WorkerPool**：基于 gRPC 的异步任务调度，支持动态扩容、主动健康检查和健康标记。
- **CLI 入口重写**：使用 `clap` 实现了 `run`、`submit`、`status` 子命令。
- **持久任务队列**：Runtime 将父任务和子任务状态追加写入 `.yizutt/runtime/tasks.jsonl`，CLI `tasks` 可在 Runtime 重启后查看最近任务状态；启动时可显式恢复未完成任务或标记为过期。
- **Sidecar 执行通路**：Rust Worker 启动 Python 子进程执行任务，通信通过标准输出 JSON 轨迹。
- **模型网关**：`model_gateway.py` 统一了 OpenAI / Anthropic / 本地模型的调用接口。
- **中文记忆检索**：双 FTS5 索引（原文字段 + 分词字段），解决了 SQLite 默认分词的中文 0 命中问题。
- **技能文件存储与质量控制**：任务执行完成后可将成功路径保存为 `SKILL.md`，并通过 draft -> verified -> active 流程做结构 replay 检查；同名或高相似技能会合并，草稿技能不会进入召回上下文；技能召回会基于标题、描述和步骤正文做加权排序。
- **工具调用循环**：`executor.py` 支持模型返回 `tool_calls`，执行受控工具后继续下一轮模型调用。
- **工具安全审计与基础沙箱**：工具执行默认拒绝写文件、命令执行、内部路径访问和命令网络访问，支持 `allowed_paths`、`allowed_commands`、`allowed_network_hosts` 显式授权；命令工具使用精简环境、超时上限、输出上限和进程组取消，并在 trace 中记录脱敏参数摘要、允许状态和拒绝原因。
- **证明性闭环**：`real_loop.py` 跑通了“提交任务 -> 模型调用 -> 写入记忆 -> 保存技能”的全链路。
- **本地 Web 面板**：`python -m yizutt_agi.panel` 可启动浏览器面板，查看 Runtime 状态和 Runtime 队列、提交任务并实时显示 trace、回放持久任务历史、查看最近记忆和技能摘要，并支持全局语言短码切换，默认 `cnzh` 中文-简体，可切换繁体中文、英语、日语、韩语、阿拉伯语、俄语。
- **最小 Leader/Orchestrator**：复杂任务可在 Python sidecar 中先生成结构化子任务计划，并通过 `plan_created` trace 返回；`execute_plan_parallel=true` 时 Runtime 会持久化计划，并按 `depends_on`、最大并发、队列深度和重试策略派发子任务。
- **主动健康检查**：Runtime `status` 会主动探测 Worker RPC 和 Python sidecar 导入状态，任务级错误返回 `status: "error"`，不再误杀 Worker。
- **开源许可证**：仓库根目录已添加 MIT `LICENSE`，README 和中文说明已同步许可证信息。
- **基础 CI**：GitHub Actions 会在 push 到 `main` 和 pull request 时运行 Rust 与 Python 基础检查，并启动本地 Web 面板做 HTML、配置 API 和历史 API smoke。
- **端到端本地 Mock Demo**：`examples/local_mock_model.py` 可提供无 API key 的确定性模型端点，README 已给出 Runtime、工具调用、记忆查询和技能生成的完整流程。
- **SQLite Graph Memory**：`memory.py` 在 FTS5 之外增加实体/关系表，自动抽取简单用户偏好、项目技术事实和 requires/improves 关系，支持带分数的跨会话图谱查询、一跳关联推理上下文，并向 executor/real_loop 注入图谱上下文。
- **稀疏向量记忆**：`memory.py` 为每条消息持久化 `memory_vectors` 稀疏 token 向量，支持 cosine 相似检索，并向 executor/real_loop 注入 vector context。
- **训练数据缓冲区**：成功执行轨迹会进入 SQLite `training_examples` 表，按简单质量规则评分并标记 accepted，为未来微调准备数据但不自动训练。
- **gRPC 流式 Trace API**：`proto/yizutt.proto` 和 Runtime/Worker 已支持 `SubmitStream`/`ExecuteStream`，CLI 可用 `submit --stream` 实时输出事件，普通 `submit` 保持兼容。
- **MCP stdio 工具接入**：新增 `mcp_client.py` 和受控 `mcp_call` 工具，默认拒绝，只有 `allow_mcp=true` 且显式配置 `mcp_servers` 时才可调用。
- **技能包安装器**：新增 `skill_market.py`、`yizutt` Python 入口和 `examples/skills/echo-skill` 包格式示例，支持从本地路径或 URL 安装技能。
- **团队记忆同步**：新增 `team_sync.py`，可导出/导入包含记忆消息和技能包的 zip bundle，在多个 Agent 工作区之间共享团队记忆。
- **技能工作流组合**：新增 `skill_composer.py` 和 `yizutt-compose` 入口，可按目标匹配已安装技能并生成 `WORKFLOW.md` 草稿。

## 三、关键文件与模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Rust Runtime 主程序 | `crates/yizutt-runtime/src/main.rs` | WorkerPool 管理、主动健康探测、持久任务日志、启动恢复、并行子任务派发、gRPC 服务启动、Sidecar 子进程拉起 |
| Protobuf 定义 | `proto/yizutt.proto` | 定义 RuntimeService、WorkerService 和健康检查字段 |
| Python 执行器 | `python/yizutt_agi/executor.py` | 被 Worker 调用的入口，负责模型调用、工具循环、基础沙箱策略、最小任务分解、写记忆、存技能 |
| 模型网关 | `python/yizutt_agi/model_gateway.py` | 多厂商 API 统一调用，启发式路由 |
| 工作记忆 | `python/yizutt_agi/memory.py` | SQLite + FTS5 双索引、图谱推理和向量记忆存储与检索 |
| 技能存储 | `python/yizutt_agi/skills.py` | 技能文件的保存、加载、质量验证和加权召回 |
| 语言解析 | `python/yizutt_agi/i18n.py` | 统一解析 `cnzh` 等语言短码、环境变量和 CLI 入口后缀 |
| 本地面板服务 | `python/yizutt_agi/panel.py` | 提供 HTTP 面板 API，代理 Runtime CLI，保存任务历史，读取 Runtime 队列、记忆和技能摘要，并用 SSE 桥接流式任务输出 |
| 本地面板页面 | `web/panel/index.html` | 浏览器 UI，用于查看状态、Runtime 队列、提交任务、实时 trace、回放任务历史、查看记忆和技能 |
| 离线闭环测试 | `python/yizutt_agi/real_loop.py` | 不依赖 Runtime 的端到端验证脚本 |

## 四、架构决策

- **Rust 负责性能敏感层**（调度、隔离、通信），**Python 负责灵活层**（模型调用、工具、记忆、技能）。
- **Worker 隔离机制**：每个 Worker 是独立子进程，有独立工作目录 `.yizutt/runtime/workers/<id>/`；Runtime 任务状态以 append-only JSONL 写入 `.yizutt/runtime/tasks.jsonl`，启动恢复同样通过追加日志记录审计。
- **内存数据非共享**：Worker 之间不直接共享内存状态，必要协作通过 Runtime 分配子任务。
- **中文分词**：`memory.py` 写入时生成 tokens，查询时命中 `messages_tokens_fts`。
- **受控工具执行**：`executor.py` 默认允许项目根目录内的读目录和读文件，但拒绝隐藏/内部目录；写文件必须显式开启 `allow_file_write`，命令必须同时开启 `allow_commands` 并命中 `allowed_commands` 白名单；网络型命令还必须开启 `allow_network` 并命中 `allowed_network_hosts`。
- **gRPC 通信**：Runtime 支持一元 `Submit` 和 server-streaming `SubmitStream`；Web 面板通过 `/api/submit-stream` 把 CLI 流式输出桥接为浏览器 SSE。

## 五、当前主要短板（需后续开发）

1. **编排能力仍需深化**：已有最小 `plan_created` 子任务计划、持久任务日志、依赖感知子任务派发、重试、最大并发、队列深度限制和启动恢复/过期策略，但还没有优先级队列和完整 backpressure。
2. **生产隔离仍需加强**：已有工具级策略、审计、命令超时取消、精简环境和网络 host 白名单，但还没有 cgroups 限制、容器隔离和系统级网络隔离。
3. **下一阶段重点**：当前明确任务队列已完成；后续优先做容器或 OS sandbox、远程 Worker、优先级队列。

## 六、当前任务队列

执行规则：按优先级从 P0 到 P4 顺序执行。完成一个任务后，同步第二、三、五、六节，并把下一个未完成任务标记为“当前执行”。

### P0-0 已完成：增加 Web 面板

**目标**：为 Yizutt AGI 增加一个最小可运行的本地 Web 面板，用于查看 Runtime 状态、提交任务、查看任务 trace、查看记忆和技能摘要，作为后续人机协作入口。

**建议涉及文件**：
- `web/` 或 `panel/`：新增前端面板代码，优先选择轻量方案，避免引入重型框架。
- `crates/yizutt-runtime/src/main.rs`：如面板需要本地 HTTP API 或静态文件服务，可在 Runtime 侧增加最小桥接能力。
- `proto/yizutt.proto`：只有在现有 `submit/status` 能力不足时才扩展，并保持向后兼容。
- `README.md`、`README_CN.md`、`CONTEXT.md`：完成后补充启动方式、访问地址和下一任务。

**验收标准**：
- 能在本地启动面板，并通过浏览器访问。
- 面板可配置 Runtime 地址，默认指向 `http://127.0.0.1:50200`。
- 面板能显示 Runtime/Worker 状态。
- 面板能提交一个任务，并展示返回结果或 trace 摘要。
- 面板能展示最近记忆和技能文件摘要，MVP 阶段允许只读。
- 不在前端暴露 OpenAI、Anthropic 或其他模型 API key。
- 提供手动验证命令：启动 Runtime、启动面板、提交任务、查看状态。

**非目标**：不做账号系统；不做远程云部署；不做复杂权限管理；不做完整任务编排 UI。

**完成情况**：已新增 `python/yizutt_agi/panel.py` 和 `web/panel/index.html`，面板通过本地 HTTP API 代理现有 Runtime CLI，可执行状态查询、任务提交、最近记忆读取和技能摘要读取。面板默认 `cnzh` 中文-简体，并可切换中文-繁体、英语、日语、韩语、阿拉伯语、俄语；阿拉伯语自动使用 RTL 布局。全局语言可通过 `--lang`、`YIZUTT_LANG` 或安装入口后缀 `yizutt-panel_cnzh` 设置。

**手动验证命令**：
- `cargo build`
- `PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`
- `RUST_LOG=info target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 4`
- `PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`
- 浏览器打开 `http://127.0.0.1:50280`，点击刷新查看 Worker，输入任务后点击提交。

### P0-1 已完成：实现最小 Leader/Orchestrator 任务分解能力

**目标**：在不重写 Runtime 架构的前提下，让复杂任务先生成结构化子任务计划，再由现有 Worker/sidecar 通路逐步执行或返回明确计划。

**建议涉及文件**：
- `proto/yizutt.proto`：如需要扩展请求/响应字段，先保持向后兼容。
- `crates/yizutt-runtime/src/main.rs`：增加最小 orchestrator 入口或在 `submit` 路径中识别 orchestration context。
- `python/yizutt_agi/executor.py`：复用现有工具循环，支持生成和执行子任务计划。
- `python/yizutt_agi/model_gateway.py`：只有在计划生成需要独立模型调用接口时才修改。
- `README.md`、`README_CN.md`、`CONTEXT.md`：完成后同步说明和下一任务。

**验收标准**：
- 现有 `yizutt-runtime submit/status` 行为不回归。
- 能提交一个复杂任务，并在 trace 中看到 `plan_created` 或等价事件。
- 子任务计划必须是结构化 JSON，至少包含 `id`、`title`、`objective`、`status`。
- MVP 可以先顺序执行子任务，不要求并行执行。
- 如果暂不执行子任务，也必须返回可复用、可持久化的明确计划。
- Python sidecar 的普通单任务路径和工具调用循环必须继续可用。
- 提供手动验证命令：一个普通任务、一个复杂任务、一个工具调用任务。

**非目标**：不做远程 Worker；不做持久队列；不做 gRPC streaming；不做复杂多 Agent 角色系统。

**完成情况**：已在 `python/yizutt_agi/executor.py` 中加入最小编排层。任务可通过 `context.orchestrate=true`、`context.mode=plan` 或复杂任务启发式触发规划，sidecar 会先生成结构化 `plan`，向 trace 输出 `plan_created` 事件，并默认返回 `plan_only` JSON。每个子任务包含 `id`、`title`、`objective`、`status`。如传入 `context.execute_plan=true`，可按顺序复用现有工具循环执行子任务。

**手动验证命令**：
- 普通任务：`target/debug/yizutt-runtime submit --task "Reply with exactly: ordinary ok" --context-json '{"provider":"openai","skill_name":"ordinary-smoke"}'`
- 复杂任务：`target/debug/yizutt-runtime submit --task "为本地面板、主动健康检查和文档更新制定三步实现计划" --context-json '{"provider":"openai","orchestrate":true,"max_subtasks":3,"skill_name":"orchestrator-smoke"}'`
- 工具调用任务：`target/debug/yizutt-runtime submit --task "Use the read_file tool to read README.md, then answer with the first heading only." --context-json '{"provider":"openai","allow_internal_paths":false,"max_tool_steps":2,"skill_name":"tool-loop-smoke"}'`

### P0-2 已完成：主动健康检查

**目标**：让 WorkerPool 不只依赖静态 `healthy` 标记，而能主动探测 worker 和 Python sidecar 是否可用。

**建议涉及文件**：
- `crates/yizutt-runtime/src/main.rs`
- `python/yizutt_agi/executor.py`
- `README.md`、`README_CN.md`、`CONTEXT.md`

**验收标准**：
- `yizutt-runtime status` 能反映主动探活结果。
- Worker 失效后能被标记为 unhealthy。
- 探活失败不应导致 Runtime 崩溃。
- 提供手动验证命令。

**完成情况**：`proto/yizutt.proto`、`crates/yizutt-runtime/src/yizutt.rs` 和 `crates/yizutt-runtime/src/main.rs` 已加入主动健康检查字段和逻辑。Runtime `status` 会调用 Worker `Health` RPC，Worker `Health` 会轻量导入 `yizutt_agi.executor` 验证 Python sidecar 可用。健康输出包含 `checked_at` 和 `last_error`。任务级模型或 provider 配置错误现在返回结构化 `status: "error"`，不会误杀 Worker；连接失败、RPC 不可达、sidecar 导入失败才会标记 unhealthy。

**手动验证命令**：
- 正常探活：`target/debug/yizutt-runtime status --addr http://127.0.0.1:50620`
- 成功任务：`target/debug/yizutt-runtime submit --addr http://127.0.0.1:50620 --session health-smoke --task "Reply with exactly: health ok" --context-json '{"provider":"local","skill_name":"health-smoke"}'`
- sidecar 失败探活：`YIZUTT_PYTHON=/bin/false target/debug/yizutt-runtime run --bind 127.0.0.1:50621 --worker-base-port 50640 --min-workers 1 --max-workers 1 --health-timeout-secs 2` 后执行 `target/debug/yizutt-runtime status --addr http://127.0.0.1:50621`，应看到 `healthy: false` 和 `last_error`。
- 任务级错误不误杀 Worker：缺少 `YIZUTT_LOCAL_MODEL_URL` 时提交 `provider=local` 任务会返回 `status: "error"`，随后 `status` 仍显示 Worker `healthy: true`。

### P1-1 已完成：工具执行安全策略增强

**目标**：在现有受控工具基础上增加更明确的安全策略，包括路径白名单、命令白名单、审计 trace 和危险操作默认拒绝。

**建议涉及文件**：
- `python/yizutt_agi/executor.py`
- `README.md`、`README_CN.md`、`CONTEXT.md`

**验收标准**：
- 默认拒绝写文件、执行命令、访问隐藏目录和内部目录。
- 可通过 context 显式授权有限能力。
- trace 中记录工具名、参数摘要、是否允许、执行结果。
- 提供拒绝路径和允许路径的手动验证命令。

**完成情况**：已在 `python/yizutt_agi/executor.py` 中补强工具策略。`tool_call` 只记录 `arguments_summary`，不再输出原始 `content` 等敏感参数；`tool_result` 会记录 `tool`、`ok`、`allowed`、`reason`、`arguments_summary` 和结果文本。路径访问先限制在项目根目录内，再受 `allowed_paths` 限制，并默认拒绝 `.git`、`.yizutt`、`__pycache__`、`target` 以及其他隐藏路径。`write_file` 需要 `allow_file_write`；`run_command` 需要 `allow_commands=true` 且命中 `allowed_commands` 白名单。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`
- 拒绝内部路径：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": ".yizutt/memory/work.sqlite3"}, {}), ensure_ascii=False))'`
- 允许普通路径：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("read_file", {"path": "README.md", "max_chars": 80}, {"allowed_paths":["."]}), ensure_ascii=False))'`
- 拒绝未授权命令：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("run_command", {"command":["python","-V"]}, {}), ensure_ascii=False))'`
- 允许白名单命令：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; print(json.dumps(execute_tool("run_command", {"command":["python","-V"]}, {"allow_commands":True,"allowed_commands":["python"]}), ensure_ascii=False))'`

### P1-2 已完成：添加开源许可证

**目标**：为公开仓库选择并添加许可证，消除 All Rights Reserved 状态。

**建议涉及文件**：
- `LICENSE`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**验收标准**：
- 仓库根目录存在 `LICENSE`。
- README 明确说明许可证。
- GitHub 能识别许可证类型。

**完成情况**：已选择 MIT License，并在仓库根目录新增标准 `LICENSE` 文件。`README.md` 和 `README_CN.md` 已说明项目使用 MIT License。

**手动验证命令**：
- `test -f LICENSE`
- `rg -n "MIT|License|许可证" LICENSE README.md README_CN.md CONTEXT.md`

### P1-3 已完成：添加 CI

**目标**：为 Rust 和 Python 的基础检查添加 GitHub Actions。

**建议涉及文件**：
- `.github/workflows/ci.yml`
- `README.md`
- `CONTEXT.md`

**验收标准**：
- CI 至少运行 `cargo check`、`cargo build`、`python -m py_compile python/yizutt_agi/*.py`。
- PR 或 push 到 main 能触发。
- README 增加 CI 状态说明或开发检查命令。

**完成情况**：已新增 `.github/workflows/ci.yml`。CI 在 push 到 `main` 和 pull request 时运行 `cargo check --workspace --locked`、`cargo build --workspace --locked` 和 `PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`。`README.md` 和 `README_CN.md` 已加入 CI badge 与检查命令说明。

**手动验证命令**：
- `cargo check --workspace --locked`
- `cargo build --workspace --locked`
- `PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py`

### P2-1 已完成：补充端到端使用示例

**目标**：把本地代理、Runtime 启动、任务提交、工具调用、记忆查询、技能文件生成串成一个可复制的 demo 流程。

**建议涉及文件**：
- `README.md`
- `README_CN.md`
- 可选：`examples/`

**验收标准**：
- 新用户可按文档跑通一次本地 mock 或真实代理 demo。
- 示例不要求暴露真实 API key。
- 明确说明生成物位于 `.yizutt/` 且不会提交。

**完成情况**：已新增 `examples/local_mock_model.py`，提供确定性本地模型端点，不需要 OpenAI/Anthropic API key。`README.md` 和 `README_CN.md` 已补充三终端端到端流程：启动 mock 模型、启动 Runtime、提交触发 `read_file` 的任务、查询 FTS5 工作记忆、确认技能文件生成，并说明 `.yizutt/` 为本地忽略目录。

**手动验证命令**：
- 终端 1：`PYTHONPATH=python python examples/local_mock_model.py --port 50990`
- 终端 2：`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:50990 target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 2`
- 终端 3：`target/debug/yizutt-runtime submit --addr http://127.0.0.1:50200 --session e2e-local --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2,"skill_name":"e2e-local-mock"}'`
- 记忆查询：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import json; mem=WorkingMemory(); print(json.dumps(mem.search_text("local mock README", limit=3), ensure_ascii=False, indent=2)); mem.close()'`
- 技能检查：`rg --files .yizutt/skills | rg "e2e-local-mock|SKILL.md"`

### P3 已完成（记忆与进化深化）

- **P3-1 已完成：技能质量验证与防膨胀**：保存技能前用简单 replay 验证可重复性，相似技能自动去重/合并，引入“草稿→验证→激活”状态机。

**完成情况**：已在 `python/yizutt_agi/skills.py` 中增强 `SkillStore.save_skill()`。技能保存时先渲染 draft，再解析生成的 `SKILL.md` 做结构 replay 检查；通过后写入 active 状态，并记录 `state_history: draft,verified,active`、`replay_check: passed`、`updated_at` 和 `similarity_score`。过弱技能保留为 `draft` 且不会被 `skill_context()` 召回。同名技能和高相似技能会合并步骤，避免技能目录无限膨胀。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py`
- 合并与激活：`PYTHONPATH=python python -c 'from yizutt_agi.skills import SkillStore; import tempfile, json; td=tempfile.TemporaryDirectory(); s=SkillStore(td.name); p1=s.save_skill("Summarize Repo", "Summarize a repository", ["Read the README", "Identify modules", "Return a concise summary"], "{}"); p2=s.save_skill("summarize-repo", "Summarize a repository", ["Read the README", "Return a concise summary", "Mention saved memory"], "{}"); items=s.list_skills(); print(json.dumps({"same_path": str(p1)==str(p2), "count": len(items), "status": items[0]["status"], "replay": items[0]["replay_check"], "context": s.skill_context("summarize repository")}, ensure_ascii=False)); td.cleanup()'`
- 草稿拒绝召回：`PYTHONPATH=python python -c 'from yizutt_agi.skills import SkillStore; import tempfile, json; td=tempfile.TemporaryDirectory(); s=SkillStore(td.name); s.save_skill("weak", "too weak", ["Do it"], "{}"); item=s.list_skills()[0]; print(json.dumps({"status": item["status"], "replay": item["replay_check"], "context": s.skill_context("weak")}, ensure_ascii=False)); td.cleanup()'`

- **P3-2 已完成：Graph Memory（知识图谱）**：在 FTS5 之上增加实体和关系存储，支持跨会话的偏好、事实和项目关联查询。

**完成情况**：已在 `python/yizutt_agi/memory.py` 中增加 `graph_entities` 和 `graph_relations` SQLite 表，以及 `upsert_entity()`、`add_relation()`、`search_graph()`、`graph_context()` API。`append_message()` 会通过轻量规则抽取用户偏好和项目技术事实，例如 `I prefer Rust...`、`Project Nexus uses SQLite...`。`executor.py` 和 `real_loop.py` 会在普通 FTS5 记忆上下文后追加命中的图谱上下文。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py`
- 图谱写入与查询：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "I prefer Rust for runtime design."); mem.append_message("s2", "user", "Project Nexus uses SQLite for memory."); print(json.dumps({"rust": mem.search_graph("Rust runtime", 5), "sqlite": mem.graph_context("Nexus SQLite", 5)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

- **P3-3 已完成：向量记忆层**：引入本地向量引擎（FAISS 或 usearch），支持语义相似检索，弥补纯关键词匹配的不足。

**完成情况**：已在 `python/yizutt_agi/memory.py` 中增加 `memory_vectors` SQLite 表，消息写入时生成无依赖的稀疏 token 向量并持久化；新增 `search_vector()` 和 `vector_context()`，用 cosine 相似度召回相关记忆。`executor.py` 和 `real_loop.py` 会在 FTS5 与 Graph Memory 之后追加命中的 Vector Memory 上下文。当前实现是便携 MVP 后端，后续可替换为 FAISS/usearch 或 embedding 模型向量。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py`
- 向量检索：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "Rust runtime workers schedule tasks locally"); mem.append_message("s2", "user", "Python skills store reusable execution steps"); hits=mem.search_vector("local task scheduler in Rust", limit=2); print(json.dumps({"top_session": hits[0]["session_id"], "top_score": round(hits[0]["score"], 3), "context": mem.vector_context("reusable Python skill", 2)}, ensure_ascii=False)); mem.close(); td.cleanup()'`

- **P3-4 已完成：训练数据收集与质量评分**：自动筛选高质量执行轨迹存入训练缓冲区，为未来 LoRA 微调做准备（不自动训练，仅收集）。

**完成情况**：已在 `python/yizutt_agi/memory.py` 中增加 `training_examples` SQLite 表、`record_training_example()`、`training_examples()` 和 `score_training_example()`。`executor.py` 与 `real_loop.py` 会在成功任务后记录训练样本，写入质量分、accepted 标记和原因列表。当前只收集候选数据，不触发 LoRA 或其他训练流程。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py`
- 训练缓冲区：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); trace={"provider":"local","model":"mock","started_at":1,"finished_at":2,"tool_steps":[{"tool":"read_file"}]}; item=mem.record_training_example("s1", "Summarize the runtime architecture", "This answer explains the runtime architecture with enough detail for reuse.", trace); print(json.dumps({"accepted": item["accepted"], "score": item["quality_score"], "stored": len(mem.training_examples(accepted_only=True))}, ensure_ascii=False)); mem.close(); td.cleanup()'`

- **P3-5 已完成：gRPC 流式 Trace API**：将当前一元返回改为 server-streaming，让调用方可实时观察 Agent 思考、工具调用和最终输出。

**完成情况**：已扩展 `proto/yizutt.proto`，新增 `TraceEvent`、`RuntimeService.SubmitStream` 和 `WorkerService.ExecuteStream`。`crates/yizutt-runtime/src/yizutt.rs` 已同步 tonic/prost 服务代码。Runtime 会代理 Worker 的流式事件；Worker 会边读取 Python sidecar stdout JSON 行边通过 gRPC stream 返回。CLI `submit --stream` 会逐条打印事件，最后一个事件带 `final: true`、聚合 trace 和最终 output。原有一元 `submit` 行为保持兼容。

**手动验证命令**：
- `cargo check --workspace --locked`
- `cargo build --workspace --locked`
- 终端 1：`PYTHONPATH=python python examples/local_mock_model.py --port 50990`
- 终端 2：`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:50990 target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 2`
- 终端 3：`target/debug/yizutt-runtime submit --stream --addr http://127.0.0.1:50200 --session stream-local --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2,"skill_name":"stream-local-mock"}'`

### P4 已完成（生态与协作）

- **P4-1 已完成：MCP 协议支持**：在模型网关或 Agent 运行时增加 MCP 客户端，使 Yizutt 能直接调用标准化外部工具（文件系统、数据库、代码解释器等）。

**完成情况**：已新增 `python/yizutt_agi/mcp_client.py`，实现最小 MCP stdio JSON-RPC client，支持 `initialize`、`tools/list` 和 `tools/call`。`executor.py` 新增受控 `mcp_call` 工具，默认拒绝；必须 `context.allow_mcp=true` 且 `context.mcp_servers` 显式配置 server command 才允许调用。新增 `examples/echo_mcp_server.py` 作为本地验证 server。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 默认拒绝：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; result=execute_tool("mcp_call", {"server":"echo","tool":"echo","arguments":{"text":"hello mcp"}}, {}); print(json.dumps(result, ensure_ascii=False))'`
- 授权调用：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; ctx={"allow_mcp":True,"mcp_servers":{"echo":{"command":["python","examples/echo_mcp_server.py"]}}}; result=execute_tool("mcp_call", {"server":"echo","tool":"echo","arguments":{"text":"hello mcp"}}, ctx); print(json.dumps(result, ensure_ascii=False))'`

- **P4-2 已完成：技能市场与社区共享**：定义技能包标准，支持 `yizutt skill install <url>` 安装别人分享的技能。

**完成情况**：已新增 `python/yizutt_agi/skill_market.py`，定义最小技能包标准：目录内包含 `skill.json` 和 `SKILL.md`，manifest 字段包含 `name`、`version`、`description`、`skill_file`。`pyproject.toml` 增加 `yizutt = "yizutt_agi.skill_market:main"` 入口。CLI 支持 `yizutt skill install <path-or-url>` 和 `yizutt skill list`；MVP 已支持本地路径、单个 `SKILL.md` 文件和远程 URL。新增 `examples/skills/echo-skill` 作为可安装示例包。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 安装示例技能包：`PYTHONPATH=python python -m yizutt_agi.skill_market skill install examples/skills/echo-skill --skills-root .yizutt/skill-test`
- 列出已安装技能包：`PYTHONPATH=python python -m yizutt_agi.skill_market skill list --skills-root .yizutt/skill-test`

- **P4-3 已完成：多 Agent 会话协作**：多个 Agent 实例可同步共享记忆和技能变更，实现“团队记忆”。

**完成情况**：已新增 `python/yizutt_agi/team_sync.py` 和 `yizutt-team` Python 入口。`export` 会把 SQLite 记忆消息和技能包打包为 `yizutt-team-bundle` zip；`import` 会合并消息和技能，导入消息走 `WorkingMemory.append_message()`，因此会重建 FTS、Graph 和 Vector 索引。MVP 采用显式 bundle 导出/导入，不做后台实时同步。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 构造源数据：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; from yizutt_agi.skills import SkillStore; mem=WorkingMemory(".yizutt/team-test/source.sqlite3"); mem.append_message("team-s1", "user", "I prefer Rust for team runtime work."); mem.append_message("team-s1", "assistant", "Noted team runtime preference."); mem.close(); SkillStore(".yizutt/team-test/source-skills").save_skill("team-echo", "Share a team echo skill", ["Read phrase", "Return phrase unchanged"], "{}")'`
- 导出：`PYTHONPATH=python python -m yizutt_agi.team_sync export --bundle .yizutt/team-test/team.zip --memory-path .yizutt/team-test/source.sqlite3 --skills-root .yizutt/team-test/source-skills`
- 导入：`PYTHONPATH=python python -m yizutt_agi.team_sync import --bundle .yizutt/team-test/team.zip --memory-path .yizutt/team-test/dest.sqlite3 --skills-root .yizutt/team-test/dest-skills`
- 验证记忆：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import json; mem=WorkingMemory(".yizutt/team-test/dest.sqlite3"); print(json.dumps({"hits": len(mem.search_text("Rust team runtime", 5)), "graph": mem.graph_context("Rust team", 5)}, ensure_ascii=False)); mem.close()'`
- 验证技能：`PYTHONPATH=python python -m yizutt_agi.skill_market skill list --skills-root .yizutt/team-test/dest-skills`

- **P4-4 已完成：跨技能组合与自动化工作流**：从多个独立技能中自动发现可串联的“技能链”，生成复合模板。

**完成情况**：已新增 `python/yizutt_agi/skill_composer.py` 和 `yizutt-compose` Python 入口。组合器会读取已安装技能，按目标 token overlap 评分，选择匹配技能链，并在 `.yizutt/workflows/<name>/WORKFLOW.md` 写入草稿 workflow，包含目标、技能链、匹配分、技能路径和执行模板。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 构造技能：`PYTHONPATH=python python -c 'from yizutt_agi.skills import SkillStore; s=SkillStore(".yizutt/compose-test/skills"); s.save_skill("read-readme", "Read README project documentation", ["Open README.md", "Extract project details"], "{}"); s.save_skill("summarize-architecture", "Summarize runtime architecture", ["Read gathered details", "Write concise architecture summary"], "{}")'`
- 组合 workflow：`PYTHONPATH=python python -m yizutt_agi.skill_composer compose --goal "Read README and summarize runtime architecture" --skills-root .yizutt/compose-test/skills --workflows-root .yizutt/compose-test/workflows`

### N1-1 已完成：Web 面板流式 Trace 消费

**目标**：让浏览器面板不再等待 Runtime 一次性返回结果，而是在任务运行时实时显示 gRPC `submit --stream` 的 trace 行，便于观察工具调用、工具结果和最终输出。

**涉及文件**：
- `python/yizutt_agi/panel.py`
- `web/panel/index.html`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：`panel.py` 新增 `/api/submit-stream` POST API，通过 `subprocess.Popen` 启动 `yizutt-runtime submit --stream`，把 stdout 按行封装为 SSE `line` 事件，并发送 `started`/`finished`/`error` 状态事件。`web/panel/index.html` 的提交按钮已改为消费 SSE stream，逐行追加 trace 输出，并在结束后刷新 Runtime 状态、最近记忆和技能摘要。该实现复用现有 CLI 和 gRPC streaming 通路，不改变 Rust 协议。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 前端静态检查：`python -c 'from pathlib import Path; text=Path("web/panel/index.html").read_text(); assert "/api/submit-stream" in text and "streamSubmit" in text; print("panel-js-ok")'`
- 终端 1：`PYTHONPATH=python python examples/local_mock_model.py --port 50990`
- 终端 2：`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:50990 target/debug/yizutt-runtime run --bind 127.0.0.1:50200 --worker-base-port 50210 --min-workers 1 --max-workers 2`
- 终端 3：`PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200`
- 浏览器打开 `http://127.0.0.1:50280`，提交 `Use the read_file tool to read README.md, then summarize the project in one sentence.`，应看到 `tool_call`、`tool_result`、`completed` 和最终 `exit_code: 0` 逐行出现。

### N1-2 已完成：Web 面板持久任务历史与 replay

**目标**：把每次从 Web 面板提交的任务、session、状态、trace 摘要和完成时间保存到本地，供浏览器回看和复盘。

**涉及文件**：
- `python/yizutt_agi/panel.py`
- `web/panel/index.html`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：`panel.py` 新增 `--history-path` / `YIZUTT_PANEL_HISTORY_PATH`，默认把面板任务历史保存到 `.yizutt/panel/history.sqlite3`。新增 `/api/history` 和 `/api/history/run?id=...` 只读 API，记录每次提交的 task、session、runtime、context、status、exit_code、stderr、trace_summary、trace_json、started_at 和 completed_at。`/api/submit-stream` 会在任务开始时创建历史记录，结束或失败时写入最终状态和可 replay 的 trace 事件；普通 `/api/submit` 也会保存一次性返回记录。`web/panel/index.html` 新增任务历史区，可刷新最近运行并点击“回放”把历史任务参数和已保存 trace 载回输出面板。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 前端静态检查：`python -c 'from pathlib import Path; text=Path("web/panel/index.html").read_text(); assert "/api/history" in text and "loadHistoryRun" in text and "historyList" in text; print("panel-history-js-ok")'`
- 历史库 API 检查：`PYTHONPATH=python python -c 'import tempfile, json; from pathlib import Path; from yizutt_agi.panel import PanelConfig, history_start_run, history_finish_run, api_history, api_history_run; td=tempfile.TemporaryDirectory(); root=Path(td.name); cfg=PanelConfig("127.0.0.1", 0, "http://127.0.0.1:50200", "yizutt-runtime", root, root, root/"runtime", root/"memory.sqlite3", root/"skills", root/"history.sqlite3", 10, "cnzh"); rid=history_start_run(cfg, cfg.runtime_addr, "s1", "hello task", "{}"); history_finish_run(cfg, rid, "completed", True, 0, "", [{"type":"line","text":"trace ok"}]); listing=api_history(cfg, "limit=5"); detail=api_history_run(cfg, f"id={rid}"); assert listing["items"][0]["id"] == rid and detail["item"]["trace"][0]["text"] == "trace ok"; print(json.dumps({"run_id": rid, "items": len(listing["items"]), "trace_count": detail["item"]["trace_count"]})); td.cleanup()'`
- 面板验证：启动 Runtime 和面板后提交一个任务，任务结束后应在“任务历史”区看到记录；点击“回放”应恢复任务、session、context 和 trace 输出。

### N1-3 已完成：生产沙箱基础隔离与网络白名单

**目标**：在现有工具级安全策略之外，为本地 Worker/sidecar 增加更接近生产环境的资源隔离和网络访问约束设计，先实现可验证的最小保护层。

**涉及文件**：
- `python/yizutt_agi/executor.py`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：`executor.py` 的 `run_command` 工具新增基础沙箱策略：命令默认仍拒绝，开启后必须命中 `allowed_commands`；命令进程使用精简环境变量，只透传 `PATH`、`HOME`、`TMPDIR`、`LANG`、`LC_ALL`、`PYTHONPATH` 和显式 `allowed_env`；`timeout_secs` 和输出大小会被策略上限钳制；超时时会取消进程组并返回 `reason: "command_timeout_cancelled"`。`curl`、`wget`、`ssh`、`scp` 等网络型命令默认拒绝，必须同时设置 `allow_network=true` 和 `allowed_network_hosts`，host 支持精确和子域匹配。所有拒绝都通过 `tool_result.reason` 返回结构化原因，不扩大默认权限。

**手动验证命令**：
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 网络默认拒绝：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; ctx={"allow_commands":True,"allowed_commands":["curl"]}; print(json.dumps(execute_tool("run_command", {"command":["curl","https://example.com"]}, ctx), ensure_ascii=False))'`
- 网络 host 白名单：`PYTHONPATH=python python -c 'from yizutt_agi.executor import _network_allowed; print(_network_allowed(["curl","https://api.example.com/v1"], {"allow_network":True,"allowed_network_hosts":["example.com"]}))'`
- 超时取消：`PYTHONPATH=python python -c 'from yizutt_agi.executor import execute_tool; import json; ctx={"allow_commands":True,"allowed_commands":["python"],"max_command_timeout_secs":1}; print(json.dumps(execute_tool("run_command", {"command":["python","-c","import time; time.sleep(2)"],"timeout_secs":5}, ctx), ensure_ascii=False))'`

### N1-4 已完成：图谱推理与技能排序增强

**目标**：增强长期记忆和技能召回质量，让图谱上下文和技能链选择不只依赖简单关键词计数。

**涉及文件**：
- `python/yizutt_agi/memory.py`
- `python/yizutt_agi/skills.py`
- `python/yizutt_agi/skill_composer.py`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：`memory.py` 的 `search_graph()` 现在为事实写入 `score`，并新增 `search_graph_reasoning()`，会在直接命中的事实之外补入一跳关联事实；`graph_context()` 输出带分数的 prompt-ready 事实。图谱抽取新增英文/中文 `requires`、`improves` 关系。`skills.py` 新增 `search_skills()`，基于技能 name、description、完整 `SKILL.md` 正文和中文 n-gram token 计算覆盖率、密度、精确匹配和轻量 recency 分；`skill_context()` 改用同一排序。`skill_composer.py` 复用 `SkillStore.search_skills()`，workflow 草稿会记录命中词和步骤数。

**手动验证命令**：
- 图谱推理：`PYTHONPATH=python python -c 'from yizutt_agi.memory import WorkingMemory; import tempfile, json; td=tempfile.TemporaryDirectory(); mem=WorkingMemory(td.name+"/work.sqlite3"); mem.append_message("s1", "user", "Project Nexus uses SQLite for memory."); mem.append_message("s1", "user", "SQLite improves graph reasoning for memory replay."); hits=mem.search_graph_reasoning("Nexus graph memory", 5); print(json.dumps({"count": len(hits), "top": hits[0]["relation"], "score": hits[0]["score"], "context": mem.graph_context("Nexus graph memory", 5)}, ensure_ascii=False)); mem.close(); td.cleanup()'`
- 技能排序：`PYTHONPATH=python python -c 'from yizutt_agi.skills import SkillStore; import tempfile, json; td=tempfile.TemporaryDirectory(); s=SkillStore(td.name); s.save_skill("graph-memory-replay", "Use graph memory for replay analysis", ["Load graph memory facts", "Rank related facts by score", "Replay the task trace"], "{}"); s.save_skill("runtime-build", "Build Rust runtime", ["Run cargo build", "Inspect worker status"], "{}"); hits=s.search_skills("graph replay memory", 3); print(json.dumps({"top": hits[0]["name"], "score": hits[0]["score"], "context": s.skill_context("graph replay memory")}, ensure_ascii=False)); td.cleanup()'`

### N1-5 已完成：CI Web 面板 Smoke 检查

**目标**：扩展 CI，覆盖本地 Web 面板最小可启动和关键只读 API，避免面板静态/HTTP 回归。

**涉及文件**：
- `.github/workflows/ci.yml`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：GitHub Actions 在 Rust build 和 Python 编译检查后启动 `python -m yizutt_agi.panel`，访问面板 HTML、`/api/config`、`/api/history?limit=2` 和 `/api/runtime-tasks?limit=2`，并静态断言前端包含 `/api/submit-stream`、`/api/history`、`/api/runtime-tasks` 和 `loadHistoryRun`。该 smoke 不依赖真实模型或正在运行的 Runtime。

**手动验证命令**：
- `cargo check --workspace --locked`
- `PYTHONPATH=python python -m yizutt_agi.panel --port 50981 --runtime-bin target/debug/yizutt-runtime --runtime-home .yizutt/ci-runtime --history-path .yizutt/ci-panel/history.sqlite3`
- `curl -fsS http://127.0.0.1:50981/ >/dev/null`
- `curl -fsS http://127.0.0.1:50981/api/config | python -m json.tool >/dev/null`
- `curl -fsS 'http://127.0.0.1:50981/api/history?limit=2' | python -m json.tool >/dev/null`
- `curl -fsS 'http://127.0.0.1:50981/api/runtime-tasks?limit=2' | python -m json.tool >/dev/null`

### N2-1 已完成：持久队列与并行子任务调度

**目标**：把当前内存调度和 plan-only 编排升级为可恢复的持久任务队列，并让结构化子任务可以按依赖关系并行派发给多个 Worker。

**涉及文件**：
- `crates/yizutt-runtime/src/main.rs`
- `python/yizutt_agi/panel.py`
- `web/panel/index.html`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：Runtime 新增 append-only `.yizutt/runtime/tasks.jsonl` 任务事件日志，普通 `submit`、`submit --stream`、父任务和子任务都会写入 queued/running/final 状态。CLI 新增 `yizutt-runtime tasks --home .yizutt/runtime --limit 20`，可在 Runtime 停止或重启后折叠 JSONL 事件并查看最新任务状态。普通 `submit` 若传入 `context.execute_plan_parallel=true` 或 `context.runtime_execute_plan_parallel=true`，Runtime 会从父任务 trace 的 `plan_created` 事件中提取计划，把每个无依赖子任务写入持久日志，并并发派发给 WorkerPool；最终回复会追加 `parallel_subtasks` 和合并 trace。Web 面板新增 `/api/runtime-tasks` 和“Runtime 队列”视图，读取同一任务日志。

**手动验证命令**：
- 构建检查：`cargo check --workspace --locked && cargo build --workspace --locked`
- 编译检查：`PYTHONPATH=python python -m py_compile python/yizutt_agi/*.py examples/local_mock_model.py examples/echo_mcp_server.py`
- 终端 1：`PYTHONPATH=python python examples/local_mock_model.py --port 51090`
- 终端 2：`PYTHONPATH=python YIZUTT_LOCAL_MODEL_URL=http://127.0.0.1:51090 target/debug/yizutt-runtime run --bind 127.0.0.1:51000 --worker-base-port 51010 --min-workers 1 --max-workers 3 --home .yizutt/n2-runtime --task-timeout-secs 60`
- 终端 3：`target/debug/yizutt-runtime submit --addr http://127.0.0.1:51000 --session n2-parallel --task "Plan and execute README review and runtime status summary" --context-json '{"provider":"local","orchestrate":true,"execute_plan_parallel":true,"max_subtasks":2,"max_tool_steps":2,"skill_name":"n2-parallel-smoke"}'`
- 队列查询：`target/debug/yizutt-runtime tasks --home .yizutt/n2-runtime --limit 10`
- 面板 API：`PYTHONPATH=python python -m yizutt_agi.panel --port 50981 --runtime-bin target/debug/yizutt-runtime --runtime-home .yizutt/n2-runtime --history-path .yizutt/ci-panel/history.sqlite3` 后执行 `curl -fsS 'http://127.0.0.1:50981/api/runtime-tasks?limit=2' | python -m json.tool >/dev/null`

### N2-2 已完成：依赖图调度与重试/背压策略

**目标**：在 N2-1 的无依赖并行派发基础上，为子任务计划增加依赖图、失败重试、最大并发和 backpressure 策略。

**涉及文件**：
- `crates/yizutt-runtime/src/main.rs`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**完成情况**：Runtime 的并行计划派发现在会先规范化子任务计划，读取可选 `depends_on` 字段并按依赖满足的 ready wave 执行。`context.max_parallel_concurrency` 控制每个 wave 的最大并发，`context.max_parallel_subtasks` 控制队列深度，超过时返回 `status: "queue_rejected"` 和 `reason: "max_parallel_subtasks_exceeded"`；`context.max_subtask_retries` 控制失败重试次数，每次 retry 都写入持久任务日志，runtime task id 使用 `:retry-N` 后缀。依赖失败或循环依赖导致无法 ready 的子任务会返回 `skipped_dependency_failed` 和缺失依赖列表。现有 `submit`、`submit --stream` 和 `tasks` CLI 保持兼容。

**手动验证命令**：
- 构建检查：`cargo check --workspace --locked && cargo build --workspace --locked`
- 端到端并行计划：沿用 N2-1 的本地 mock 验证命令，并在 context 中加入 `"max_parallel_concurrency":2,"max_parallel_subtasks":8,"max_subtask_retries":1`
- 队列深度拒绝：提交包含超过 `max_parallel_subtasks` 的计划或把 `max_parallel_subtasks` 设为 1，最终 `parallel_subtasks` 应返回 `queue_rejected`

### N2-3 已完成：长期运行任务恢复执行

**目标**：在已有持久任务日志基础上，让 Runtime 启动后能发现未完成任务，并按策略恢复或标记过期。

**涉及文件**：
- `crates/yizutt-runtime/src/main.rs`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**验收标准**：
- Runtime 启动时能读取 `tasks.jsonl` 并识别 queued/running 但无最终状态的任务。
- 可配置 `resume_incomplete_tasks` 或 `expire_incomplete_tasks`。
- 恢复/过期动作写入新的持久日志记录。
- 不破坏现有 `submit`、`submit --stream`、`tasks` CLI。

**完成情况**：Runtime `run` 新增 `--resume-incomplete-tasks` 和 `--expire-incomplete-tasks` 两个互斥启动参数。启动时会读取 `.yizutt/runtime/tasks.jsonl` 的最新任务记录，识别未进入最终状态的 queued/running/recovery 任务；过期模式会追加 `expired_on_startup` 审计记录，恢复模式会追加 `recovery_queued` 后重新派发顶层任务或子任务。恢复执行复用原有 WorkerPool、任务上下文和 `dispatch_runtime_task` 通路，现有 `submit`、`submit --stream` 和 `tasks` CLI 保持兼容。

**手动验证命令**：
- 构建检查：`cargo check --workspace --locked && cargo build --workspace --locked`
- 过期恢复：写入一个 queued 任务到临时 `tasks.jsonl`，启动 `target/debug/yizutt-runtime run --home .yizutt/recovery-test --expire-incomplete-tasks` 后，`target/debug/yizutt-runtime tasks --home .yizutt/recovery-test --limit 5` 应显示 `expired_on_startup`
- 恢复执行：启动 `examples/local_mock_model.py`，写入一个带本地 provider/context 的 queued 任务，启动 `target/debug/yizutt-runtime run --home .yizutt/recovery-resume-test --resume-incomplete-tasks` 后，`tasks` 应显示该任务最终进入 `ok`

### N2-4 建议任务：容器或 OS sandbox Worker 隔离

**目标**：在现有工具级策略和 Worker 子进程隔离基础上，增加可选的系统级隔离边界，降低命令工具和 sidecar 执行的生产风险。

**建议涉及文件**：
- `crates/yizutt-runtime/src/main.rs`
- `python/yizutt_agi/executor.py`
- `README.md`
- `README_CN.md`
- `CONTEXT.md`

**验收标准**：
- Runtime/Worker 支持显式开启的 sandbox profile，默认仍保持当前本地开发行为。
- 可限制 Worker 工作目录、环境变量、进程资源或网络访问，并在不支持的平台返回清晰错误。
- `status` 或任务 trace 能暴露当前 sandbox profile 与失败原因。
- 不破坏现有本地 mock demo、`submit`、`submit --stream`、`tasks` CLI。

### 当前任务状态

截至本次更新，P0 到 P4 队列、N1-1 Web 面板流式 trace 消费、N1-2 Web 面板持久任务历史与 replay、N1-3 生产沙箱基础隔离与网络白名单、N1-4 图谱推理与技能排序增强、N1-5 CI Web 面板 smoke 检查、N2-1 持久队列与并行子任务调度、N2-2 依赖图调度与重试/背压策略、N2-3 长期运行任务恢复执行均已完成。下一个建议任务是 N2-4：容器或 OS sandbox Worker 隔离。

## 七、常用开发命令

```bash
# 构建 Rust
cargo build

# 启动 Runtime（自定义端口）
cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200 --health-timeout-secs 3

# 提交任务
cargo run -p yizutt-runtime -- submit --task "你的任务描述" --addr http://127.0.0.1:50200

# 查看状态
cargo run -p yizutt-runtime -- status --addr http://127.0.0.1:50200

# 查看 Runtime 持久任务队列
cargo run -p yizutt-runtime -- tasks --home .yizutt/runtime --limit 20

# 复杂任务规划
cargo run -p yizutt-runtime -- submit --task "为本地面板、主动健康检查和文档更新制定三步实现计划" --context-json '{"provider":"openai","orchestrate":true,"max_subtasks":3}'

# 启动本地 Web 面板
PYTHONPATH=python python -m yizutt_agi.panel --port 50280 --runtime-addr http://127.0.0.1:50200

# Python 离线闭环测试
python -m yizutt_agi.real_loop

# 编译检查 Python 文件
python -m py_compile python/yizutt_agi/*.py
```

## 八、环境依赖

- Rust 稳定版
- Python 3.11+
- 本地需可绑定回环端口
- 可选：OpenAI API Key、Anthropic API Key 或 OpenAI-compatible 本地代理

## 九、AI 助手行为准则

- 任何代码修改完成后，必须在会话结束前更新本文件的“最后更新”日期。
- 若任务导致状态变化，必须同步更新第二、三、五节。
- 如果第六节任务完成，重新审视第五节中剩余的第一个待解决短板，并在第六节写入下一个任务。
- 更新完成后输出一句话：`CONTEXT.md 已同步`，并说明下一个任务是什么。

---

最后更新：2026-05-09
