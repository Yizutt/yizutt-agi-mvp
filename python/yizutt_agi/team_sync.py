import argparse
import json
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any

from .memory import WorkingMemory
from .skill_market import DEFAULT_SKILL_FILE, install_text


def export_bundle(
    bundle_path: str | Path,
    memory_path: str | Path = ".yizutt/memory/work.sqlite3",
    skills_root: str | Path = ".yizutt/skills",
) -> dict[str, Any]:
    bundle = Path(bundle_path)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    memory_items = export_messages(memory_path)
    skill_items = export_skills(skills_root)
    manifest = {
        "format": "yizutt-team-bundle",
        "version": "0.1.0",
        "created_at": int(time.time()),
        "memory_items": len(memory_items),
        "skill_items": len(skill_items),
    }
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("memory/messages.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in memory_items))
        for item in skill_items:
            archive.writestr(f"skills/{item['name']}/{DEFAULT_SKILL_FILE}", item["text"])
            archive.writestr(f"skills/{item['name']}/skill.json", json.dumps(item["manifest"], ensure_ascii=False, indent=2) + "\n")
    return {"bundle": str(bundle), **manifest}


def import_bundle(
    bundle_path: str | Path,
    memory_path: str | Path = ".yizutt/memory/work.sqlite3",
    skills_root: str | Path = ".yizutt/skills",
) -> dict[str, Any]:
    bundle = Path(bundle_path)
    imported_messages = 0
    skipped_messages = 0
    imported_skills = 0
    memory = WorkingMemory(memory_path)
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            message_data = archive.read("memory/messages.jsonl").decode("utf-8") if "memory/messages.jsonl" in archive.namelist() else ""
            for line in message_data.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if message_exists(memory, item["session_id"], item["role"], item["content"]):
                    skipped_messages += 1
                    continue
                memory.append_message(item["session_id"], item["role"], item["content"], item.get("meta", {}))
                imported_messages += 1
            for name in skill_names(archive):
                text = archive.read(f"skills/{name}/{DEFAULT_SKILL_FILE}").decode("utf-8")
                manifest_path = f"skills/{name}/skill.json"
                manifest = {}
                if manifest_path in archive.namelist():
                    manifest = json.loads(archive.read(manifest_path).decode("utf-8"))
                install_text(text, manifest or {"name": name}, f"bundle:{bundle}", skills_root)
                imported_skills += 1
    finally:
        memory.close()
    return {
        "bundle": str(bundle),
        "imported_messages": imported_messages,
        "skipped_messages": skipped_messages,
        "imported_skills": imported_skills,
    }


def export_messages(memory_path: str | Path) -> list[dict[str, Any]]:
    path = Path(memory_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select session_id, role, content, meta_json, created_at
            from messages
            where role in ('user', 'assistant', 'trace')
            order by created_at asc
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "meta": json.loads(row["meta_json"] or "{}"),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def export_skills(skills_root: str | Path) -> list[dict[str, Any]]:
    root = Path(skills_root)
    items = []
    for path in sorted(root.glob(f"*/{DEFAULT_SKILL_FILE}")):
        manifest_path = path.parent / "skill.json"
        manifest = {"name": path.parent.name, "skill_file": DEFAULT_SKILL_FILE}
        if manifest_path.exists():
            manifest.update(json.loads(manifest_path.read_text(encoding="utf-8")))
        items.append({"name": path.parent.name, "text": path.read_text(encoding="utf-8"), "manifest": manifest})
    return items


def message_exists(memory: WorkingMemory, session_id: str, role: str, content: str) -> bool:
    row = memory.db.execute(
        "select 1 from messages where session_id = ? and role = ? and content = ? limit 1",
        (session_id, role, content),
    ).fetchone()
    return row is not None


def skill_names(archive: zipfile.ZipFile) -> list[str]:
    names = set()
    for name in archive.namelist():
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == "skills" and parts[2] == DEFAULT_SKILL_FILE:
            names.add(parts[1])
    return sorted(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or import Yizutt team memory bundles.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    export_cmd = subcommands.add_parser("export", help="Export memory and skills to a team bundle.")
    export_cmd.add_argument("--bundle", required=True)
    export_cmd.add_argument("--memory-path", default=".yizutt/memory/work.sqlite3")
    export_cmd.add_argument("--skills-root", default=".yizutt/skills")
    import_cmd = subcommands.add_parser("import", help="Import a team bundle into this workspace.")
    import_cmd.add_argument("--bundle", required=True)
    import_cmd.add_argument("--memory-path", default=".yizutt/memory/work.sqlite3")
    import_cmd.add_argument("--skills-root", default=".yizutt/skills")
    args = parser.parse_args(argv)

    if args.command == "export":
        print(json.dumps({"ok": True, **export_bundle(args.bundle, args.memory_path, args.skills_root)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "import":
        print(json.dumps({"ok": True, **import_bundle(args.bundle, args.memory_path, args.skills_root)}, ensure_ascii=False, indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
