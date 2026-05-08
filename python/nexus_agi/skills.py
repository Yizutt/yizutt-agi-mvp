import re
import time
from pathlib import Path


class SkillStore:
    def __init__(self, root: str | Path = ".nexus/skills") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_skill(self, name: str, description: str, steps: list[str], source_trace: str = "") -> Path:
        safe_name = self._safe_name(name)
        skill_dir = self.root / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = [
            "---",
            f"name: {safe_name}",
            f"description: {description}",
            f"created_at: {int(time.time())}",
            "---",
            "",
            "触发条件:",
            description,
            "",
            "执行步骤:",
        ]
        body.extend(f"{idx + 1}. {step}" for idx, step in enumerate(steps))
        if source_trace:
            body.extend(["", "来源轨迹:", source_trace])
        path = skill_dir / "SKILL.md"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        return path

    def list_skills(self) -> list[dict]:
        result = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            result.append({
                "name": path.parent.name,
                "path": str(path),
                "description": self._frontmatter_value(text, "description"),
            })
        return result

    def load_skill(self, name: str) -> str:
        path = self.root / self._safe_name(name) / "SKILL.md"
        return path.read_text(encoding="utf-8")

    def skill_context(self, query: str) -> str:
        terms = set(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", query.lower()))
        matches = []
        for item in self.list_skills():
            haystack = f"{item['name']} {item['description']}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                matches.append((score, item))
        matches.sort(key=lambda pair: pair[0], reverse=True)
        return "\n".join(f"{item['name']}: {item['description']}" for _, item in matches[:5])

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
        if not cleaned:
            raise ValueError("skill name is empty")
        return cleaned[:80]

    @staticmethod
    def _frontmatter_value(text: str, key: str) -> str:
        for line in text.splitlines():
            if line.startswith(f"{key}:"):
                return line.split(":", 1)[1].strip()
        return ""

