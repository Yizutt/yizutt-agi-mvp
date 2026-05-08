# CONTEXT.md — Yizutt AGI MVP 项目状态

本文档供 AI 助手快速理解项目结构、约束和当前任务。执行任务时以第六节为当前目标。

## 一、项目简介

Yizutt AGI 是一个自进化、多 Agent 协作的 AI 队友框架，采用 Rust 核心运行时 + Python 技能层的混合架构。目标是实现本地优先、模型无关、越用越聪明的个人 AI 助手。

## 二、已完成的核心特性

- **项目更名**：对外项目名已从旧名称迁移为 Yizutt AGI。
- **Rust Runtime & WorkerPool**：基于 gRPC 的异步任务调度，支持动态扩容、健康标记。
- **CLI 入口重写**：使用 `clap` 实现了 `run`、`submit`、`status` 子命令。
- **Sidecar 执行通路**：Rust Worker 启动 Python 子进程执行任务，通信通过标准输出 JSON 轨迹。
- **模型网关**：`model_gateway.py` 统一了 OpenAI / Anthropic / 本地模型的调用接口。
- **中文记忆检索**：双 FTS5 索引（原文字段 + 分词字段），解决了 SQLite 默认分词的中文 0 命中问题。
- **技能文件存储**：任务执行完成后可将成功路径保存为 `SKILL.md`。
- **工具调用循环**：`executor.py` 支持模型返回 `tool_calls`，执行受控工具后继续下一轮模型调用。
- **证明性闭环**：`real_loop.py` 跑通了“提交任务 -> 模型调用 -> 写入记忆 -> 保存技能”的全链路。

## 三、关键文件与模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Rust Runtime 主程序 | `crates/yizutt-runtime/src/main.rs` | WorkerPool 管理、gRPC 服务启动、Sidecar 子进程拉起 |
| Protobuf 定义 | `proto/yizutt.proto` | 定义 RuntimeService 和 WorkerService |
| Python 执行器 | `python/yizutt_agi/executor.py` | 被 Worker 调用的入口，负责调用模型、执行工具、写记忆、存技能 |
| 模型网关 | `python/yizutt_agi/model_gateway.py` | 多厂商 API 统一调用，启发式路由 |
| 工作记忆 | `python/yizutt_agi/memory.py` | SQLite + FTS5 双索引存储与检索 |
| 技能存储 | `python/yizutt_agi/skills.py` | 技能文件的保存和加载 |
| 离线闭环测试 | `python/yizutt_agi/real_loop.py` | 不依赖 Runtime 的端到端验证脚本 |

## 四、架构决策

- **Rust 负责性能敏感层**（调度、隔离、通信），**Python 负责灵活层**（模型调用、工具、记忆、技能）。
- **Worker 隔离机制**：每个 Worker 是独立子进程，有独立工作目录 `.yizutt/runtime/workers/<id>/`。
- **内存数据非共享**：Worker 之间不直接共享内存状态，必要协作通过 Runtime 分配子任务。
- **中文分词**：`memory.py` 写入时生成 tokens，查询时命中 `messages_tokens_fts`。
- **受控工具执行**：`executor.py` 默认允许读目录和读文件，写文件与命令执行必须显式授权。
- **gRPC 通信**：目前仅支持一元调用（请求-响应），流式 API 在 Roadmap 中。

## 五、当前主要短板（需后续开发）

1. **无任务分解能力**：Runtime 没有 Leader/Orchestrator 将复杂任务拆分为子任务。
2. **健康检查简单**：仅静态布尔标记，无主动探活。
3. **安全沙箱薄弱**：无 cgroups 限制、无网络白名单、无操作审计。
4. **项目缺少许可证**：目前法律上是 All Rights Reserved。

## 六、当前任务队列

执行规则：按优先级从 P0 到 P2 顺序执行。完成一个任务后，同步第二、三、五、六节，并把下一个未完成任务标记为“当前执行”。

### P0-0 当前执行：增加 Wed 面板

**目标**：为 Yizutt AGI 增加一个最小可运行的本地 Wed 面板，用于查看 Runtime 状态、提交任务、查看任务 trace、查看记忆和技能摘要，作为后续人机协作入口。

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

### P0-1 待执行：实现最小 Leader/Orchestrator 任务分解能力

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

### P0-2 待执行：主动健康检查

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

### P1-1 待执行：工具执行安全策略增强

**目标**：在现有受控工具基础上增加更明确的安全策略，包括路径白名单、命令白名单、审计 trace 和危险操作默认拒绝。

**建议涉及文件**：
- `python/yizutt_agi/executor.py`
- `README.md`、`README_CN.md`、`CONTEXT.md`

**验收标准**：
- 默认拒绝写文件、执行命令、访问隐藏目录和内部目录。
- 可通过 context 显式授权有限能力。
- trace 中记录工具名、参数摘要、是否允许、执行结果。
- 提供拒绝路径和允许路径的手动验证命令。

### P1-2 待执行：添加开源许可证

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

### P1-3 待执行：添加 CI

**目标**：为 Rust 和 Python 的基础检查添加 GitHub Actions。

**建议涉及文件**：
- `.github/workflows/ci.yml`
- `README.md`
- `CONTEXT.md`

**验收标准**：
- CI 至少运行 `cargo check`、`cargo build`、`python -m py_compile python/yizutt_agi/*.py`。
- PR 或 push 到 main 能触发。
- README 增加 CI 状态说明或开发检查命令。

### P2-1 待执行：补充端到端使用示例

**目标**：把本地代理、Runtime 启动、任务提交、工具调用、记忆查询、技能文件生成串成一个可复制的 demo 流程。

**建议涉及文件**：
- `README.md`
- `README_CN.md`
- 可选：`examples/`

**验收标准**：
- 新用户可按文档跑通一次本地 mock 或真实代理 demo。
- 示例不要求暴露真实 API key。
- 明确说明生成物位于 `.yizutt/` 且不会提交。

## 七、常用开发命令

```bash
# 构建 Rust
cargo build

# 启动 Runtime（自定义端口）
cargo run -p yizutt-runtime -- run --bind 127.0.0.1:50200

# 提交任务
cargo run -p yizutt-runtime -- submit --task "你的任务描述" --addr http://127.0.0.1:50200

# 查看状态
cargo run -p yizutt-runtime -- status --addr http://127.0.0.1:50200

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

最后更新：2026-05-08
