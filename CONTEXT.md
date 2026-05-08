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

## 六、当前任务

**任务**：实现最小任务分解能力，为复杂任务提供 Leader/Orchestrator 入口。
**涉及文件**：待定，预计包含 `crates/yizutt-runtime/src/main.rs`、`proto/yizutt.proto`、`python/yizutt_agi/executor.py`。
**验收标准**：能提交一个复杂任务并拆成多个子任务执行或生成明确子任务计划；trace 中能看到分解结果；不破坏现有 `submit/status` 和 sidecar 执行通路。

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
