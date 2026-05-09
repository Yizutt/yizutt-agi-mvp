import re
import time
from pathlib import Path


ACTIVE_SKILL_STATUSES = {"active", "verified"}
SIMILARITY_THRESHOLD = 0.72


class SkillStore:
    def __init__(self, root: str | Path = ".yizutt/skills") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_skill(self, name: str, description: str, steps: list[str], source_trace: str = "") -> Path:
        safe_name = self._safe_name(name)
        description = self._single_line(description)
        normalized_steps = self._normalize_steps(steps)
        if not normalized_steps:
            raise ValueError("skill steps are empty")

        similar = self._find_similar_skill(safe_name, description, normalized_steps)
        merged_from = ""
        similarity = 1.0
        if similar:
            target_name = similar["name"]
            existing_text = (self.root / target_name / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            existing_steps = self._steps_from_text(existing_text)
            existing_description = self._frontmatter_value(existing_text, "description")
            normalized_steps = self._merge_steps(existing_steps, normalized_steps)
            description = existing_description or description
            similarity = float(similar["score"])
            if target_name != safe_name:
                merged_from = safe_name
            safe_name = target_name

        skill_dir = self.root / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / "SKILL.md"
        created_at = self._existing_created_at(path)
        now = int(time.time())

        draft_text = self._render_skill(
            safe_name,
            description,
            normalized_steps,
            source_trace,
            status="draft",
            created_at=created_at or now,
            updated_at=now,
            replay_check="pending",
            merged_from=merged_from,
            similarity=similarity,
        )
        verification = self._verify_skill_text(draft_text)
        if not verification["ok"]:
            path.write_text(
                self._render_skill(
                    safe_name,
                    description,
                    normalized_steps,
                    source_trace,
                    status="draft",
                    created_at=created_at or now,
                    updated_at=now,
                    replay_check="failed",
                    verification_errors=verification["errors"],
                    merged_from=merged_from,
                    similarity=similarity,
                ),
                encoding="utf-8",
            )
            return path

        path.write_text(
            self._render_skill(
                safe_name,
                description,
                normalized_steps,
                source_trace,
                status="verified",
                created_at=created_at or now,
                updated_at=now,
                verified_at=now,
                replay_check="passed",
                merged_from=merged_from,
                similarity=similarity,
            ),
            encoding="utf-8",
        )
        path.write_text(
            self._render_skill(
                safe_name,
                description,
                normalized_steps,
                source_trace,
                status="active",
                created_at=created_at or now,
                updated_at=now,
                verified_at=now,
                replay_check="passed",
                merged_from=merged_from,
                similarity=similarity,
            ),
            encoding="utf-8",
        )
        return path

    def list_skills(self) -> list[dict]:
        result = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            result.append({
                "name": path.parent.name,
                "path": str(path),
                "description": self._frontmatter_value(text, "description"),
                "status": self._frontmatter_value(text, "status") or "active",
                "replay_check": self._frontmatter_value(text, "replay_check"),
                "updated_at": self._frontmatter_value(text, "updated_at"),
            })
        return result

    def load_skill(self, name: str) -> str:
        path = self.root / self._safe_name(name) / "SKILL.md"
        return path.read_text(encoding="utf-8")

    def skill_context(self, query: str) -> str:
        return "\n".join(
            f"{item['name']}: {item['description']} (score: {item['score']:.3f})"
            for item in self.search_skills(query, limit=5)
        )

    def search_skills(self, query: str, limit: int = 5) -> list[dict]:
        query_terms = self._tokens(query)
        matches = []
        for item in self.list_skills():
            if item.get("status") not in ACTIVE_SKILL_STATUSES:
                continue
            text = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
            skill_terms = self._tokens(" ".join([item["name"], item.get("description", ""), text]))
            if not query_terms or not skill_terms:
                continue
            overlap = query_terms & skill_terms
            if not overlap:
                continue
            coverage = len(overlap) / max(1, len(query_terms))
            density = len(overlap) / max(1, len(skill_terms))
            exact_bonus = 0.15 if query.lower().strip() and query.lower().strip() in text.lower() else 0.0
            recency = self._safe_int(item.get("updated_at")) / max(1, int(time.time()))
            score = (coverage * 0.7) + (density * 0.15) + exact_bonus + min(0.1, recency * 0.1)
            enriched = {
                **item,
                "score": round(score, 3),
                "matched_terms": sorted(overlap)[:12],
                "step_count": len(self._steps_from_text(text)),
            }
            matches.append(enriched)
        matches.sort(key=lambda item: (item["score"], item.get("updated_at", ""), item["name"]), reverse=True)
        return matches[:limit]

    def _find_similar_skill(self, safe_name: str, description: str, steps: list[str]) -> dict | None:
        candidate_text = " ".join([safe_name, description, *steps])
        candidate_tokens = self._tokens(candidate_text)
        best: dict | None = None
        for item in self.list_skills():
            if item.get("status") not in ACTIVE_SKILL_STATUSES:
                continue
            if item["name"] == safe_name:
                return {"name": item["name"], "score": 1.0}
            text = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
            existing_tokens = self._tokens(" ".join([item["name"], item["description"], text]))
            score = self._similarity(candidate_tokens, existing_tokens)
            if score >= SIMILARITY_THRESHOLD and (best is None or score > best["score"]):
                best = {"name": item["name"], "score": score}
        return best

    def _render_skill(
        self,
        name: str,
        description: str,
        steps: list[str],
        source_trace: str,
        status: str,
        created_at: int,
        updated_at: int,
        replay_check: str,
        verified_at: int | None = None,
        verification_errors: list[str] | None = None,
        merged_from: str = "",
        similarity: float = 1.0,
    ) -> str:
        frontmatter = [
            "---",
            f"name: {name}",
            f"description: {description}",
            f"status: {status}",
            f"state_history: {self._state_history(status, replay_check)}",
            f"created_at: {created_at}",
            f"updated_at: {updated_at}",
            f"replay_check: {replay_check}",
            f"similarity_score: {similarity:.3f}",
        ]
        if verified_at:
            frontmatter.append(f"verified_at: {verified_at}")
        if merged_from:
            frontmatter.append(f"merged_from: {merged_from}")
        if verification_errors:
            frontmatter.append(f"verification_errors: {'; '.join(verification_errors)}")
        body = [
            *frontmatter,
            "---",
            "",
            "技能状态:",
            status,
            "",
            "触发条件:",
            description,
            "",
            "执行步骤:",
        ]
        body.extend(f"{idx + 1}. {step}" for idx, step in enumerate(steps))
        if source_trace:
            body.extend(["", "来源轨迹:", source_trace])
        return "\n".join(body) + "\n"

    @staticmethod
    def _state_history(status: str, replay_check: str) -> str:
        if status == "draft" and replay_check == "failed":
            return "draft"
        if status == "verified":
            return "draft,verified"
        if status == "active":
            return "draft,verified,active"
        return status

    def _verify_skill_text(self, text: str) -> dict:
        errors = []
        name = self._frontmatter_value(text, "name")
        description = self._frontmatter_value(text, "description")
        steps = self._steps_from_text(text)
        if not name:
            errors.append("missing_name")
        if not description:
            errors.append("missing_description")
        if len(steps) < 2:
            errors.append("too_few_steps")
        if sum(len(step) for step in steps) < 24:
            errors.append("steps_too_short")
        if "执行步骤:" not in text:
            errors.append("missing_steps_section")
        return {"ok": not errors, "errors": errors}

    @staticmethod
    def _normalize_steps(steps: list[str]) -> list[str]:
        normalized = []
        for step in steps:
            text = re.sub(r"\s+", " ", str(step)).strip(" -")
            if text:
                normalized.append(text)
        return normalized[:20]

    @staticmethod
    def _merge_steps(existing: list[str], incoming: list[str]) -> list[str]:
        result = []
        seen = set()
        for step in [*existing, *incoming]:
            key = step.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(step)
        return result[:20]

    @staticmethod
    def _steps_from_text(text: str) -> list[str]:
        if "执行步骤:" not in text:
            return []
        step_text = text.split("执行步骤:", 1)[1].split("\n来源轨迹:", 1)[0]
        steps = []
        for line in step_text.splitlines():
            match = re.match(r"\s*\d+\.\s+(.*)", line)
            if match:
                steps.append(match.group(1).strip())
        return steps

    @staticmethod
    def _tokens(text: str) -> set[str]:
        tokens: set[str] = set()
        for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                tokens.add(part)
                chars = list(part)
                tokens.update(chars)
                for size in range(2, 5):
                    for idx in range(0, max(0, len(chars) - size + 1)):
                        tokens.add("".join(chars[idx : idx + size]))
            else:
                tokens.add(part)
        return {token for token in tokens if token}

    @staticmethod
    def _similarity(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    @staticmethod
    def _single_line(text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip()

    def _existing_created_at(self, path: Path) -> int | None:
        if not path.exists():
            return None
        value = self._frontmatter_value(path.read_text(encoding="utf-8", errors="replace"), "created_at")
        try:
            return int(value)
        except ValueError:
            return None

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

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
