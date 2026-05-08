import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from .skills import SkillStore


PACKAGE_FILE = "skill.json"
DEFAULT_SKILL_FILE = "SKILL.md"


def install_skill(source: str, skills_root: str | Path = ".yizutt/skills") -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        return install_skill_url(source, skills_root)
    source_path = resolve_source(source)
    if source_path.is_dir():
        package_dir = source_path
        manifest = read_manifest(package_dir)
        skill_file = package_dir / manifest.get("skill_file", DEFAULT_SKILL_FILE)
        if not skill_file.exists():
            raise FileNotFoundError(f"skill file not found: {skill_file}")
        return install_from_files(skill_file, manifest, source, skills_root)

    if source_path.is_file():
        if source_path.name == PACKAGE_FILE:
            manifest = json.loads(source_path.read_text(encoding="utf-8"))
            skill_file = source_path.parent / manifest.get("skill_file", DEFAULT_SKILL_FILE)
            if not skill_file.exists():
                raise FileNotFoundError(f"skill file not found: {skill_file}")
            return install_from_files(skill_file, manifest, source, skills_root)
        text = source_path.read_text(encoding="utf-8")
        manifest = manifest_from_skill_text(text, source_path.stem)
        return install_text(text, manifest, source, skills_root)

    raise FileNotFoundError(source)


def install_skill_url(url: str, skills_root: str | Path = ".yizutt/skills") -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    if url.endswith(PACKAGE_FILE):
        manifest = json.loads(text)
        skill_url = manifest.get("skill_url") or manifest.get("skill_file_url")
        if not skill_url:
            raise ValueError("remote skill.json must include skill_url or skill_file_url")
        with urllib.request.urlopen(skill_url, timeout=30) as response:
            skill_text = response.read().decode("utf-8")
        return install_text(skill_text, manifest, url, skills_root)
    manifest = manifest_from_skill_text(text, Path(url).stem or "remote-skill")
    return install_text(text, manifest, url, skills_root)


def install_from_files(skill_file: Path, manifest: dict[str, Any], source: str, skills_root: str | Path) -> dict[str, Any]:
    return install_text(skill_file.read_text(encoding="utf-8"), manifest, source, skills_root)


def install_text(text: str, manifest: dict[str, Any], source: str, skills_root: str | Path) -> dict[str, Any]:
    store = SkillStore(skills_root)
    safe_name = store._safe_name(str(manifest.get("name") or frontmatter_value(text, "name") or "imported-skill"))
    target_dir = Path(skills_root) / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_path = target_dir / DEFAULT_SKILL_FILE
    skill_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    installed_manifest = {
        "name": safe_name,
        "version": str(manifest.get("version") or "0.1.0"),
        "description": str(manifest.get("description") or frontmatter_value(text, "description")),
        "skill_file": DEFAULT_SKILL_FILE,
        "source": source,
        "installed_at": int(time.time()),
    }
    (target_dir / PACKAGE_FILE).write_text(json.dumps(installed_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"name": safe_name, "path": str(skill_path), "manifest": installed_manifest}


def list_installed(skills_root: str | Path = ".yizutt/skills") -> list[dict[str, Any]]:
    root = Path(skills_root)
    items = []
    for path in sorted(root.glob(f"*/{DEFAULT_SKILL_FILE}")):
        manifest_path = path.parent / PACKAGE_FILE
        manifest = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8", errors="replace")
        items.append({
            "name": path.parent.name,
            "path": str(path),
            "version": manifest.get("version", ""),
            "description": manifest.get("description") or frontmatter_value(text, "description"),
            "source": manifest.get("source", ""),
        })
    return items


def read_manifest(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / PACKAGE_FILE
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    skill_file = package_dir / DEFAULT_SKILL_FILE
    if not skill_file.exists():
        raise FileNotFoundError(f"skill package needs {PACKAGE_FILE} or {DEFAULT_SKILL_FILE}: {package_dir}")
    return manifest_from_skill_text(skill_file.read_text(encoding="utf-8"), package_dir.name)


def manifest_from_skill_text(text: str, fallback_name: str) -> dict[str, Any]:
    return {
        "name": frontmatter_value(text, "name") or fallback_name,
        "version": frontmatter_value(text, "version") or "0.1.0",
        "description": frontmatter_value(text, "description"),
        "skill_file": DEFAULT_SKILL_FILE,
    }


def resolve_source(source: str) -> Path:
    return Path(source).expanduser().resolve()


def frontmatter_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yizutt", description="Yizutt AGI utility CLI.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    skill = subcommands.add_parser("skill", help="Manage skill packages.")
    skill_subcommands = skill.add_subparsers(dest="skill_command", required=True)
    install = skill_subcommands.add_parser("install", help="Install a skill package from a path or URL.")
    install.add_argument("source")
    install.add_argument("--skills-root", default=".yizutt/skills")
    list_cmd = skill_subcommands.add_parser("list", help="List installed skill packages.")
    list_cmd.add_argument("--skills-root", default=".yizutt/skills")
    args = parser.parse_args(argv)

    if args.command == "skill" and args.skill_command == "install":
        if args.source.startswith(("http://", "https://")):
            result = install_skill_url(args.source, args.skills_root)
        else:
            result = install_skill(args.source, args.skills_root)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "skill" and args.skill_command == "list":
        print(json.dumps({"ok": True, "items": list_installed(args.skills_root)}, ensure_ascii=False, indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
