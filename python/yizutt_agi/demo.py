from yizutt_agi import YizuttRuntimeClient, SkillStore, WorkingMemory


def main() -> None:
    memory = WorkingMemory()
    skills = SkillStore()
    session_id = memory.start_session("demo")
    client = YizuttRuntimeClient()
    result = client.submit("summarize repo architecture", session_id=session_id)
    memory.append_message(session_id, "user", "summarize repo architecture")
    memory.append_message(session_id, "assistant", result["output"], {"trace": result["trace"]})
    skills.save_skill(
        name="summarize-architecture",
        description="复用成功的源码架构总结路径",
        steps=["定位入口和模块边界", "提取通信协议", "确认持久化和隔离机制", "输出可复用模式"],
        source_trace=result["task_id"],
    )
    print(result)


if __name__ == "__main__":
    main()

