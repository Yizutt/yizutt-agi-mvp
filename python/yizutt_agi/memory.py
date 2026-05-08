import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable


class WorkingMemory:
    def __init__(self, path: str | Path = ".yizutt/memory/work.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.db.executescript(
            """
            pragma journal_mode = wal;
            create table if not exists sessions(
              id text primary key,
              title text,
              created_at integer not null,
              updated_at integer not null
            );
            create table if not exists messages(
              id text primary key,
              session_id text not null,
              role text not null,
              content text not null,
              tokens text not null default '',
              meta_json text not null default '{}',
              created_at integer not null,
              foreign key(session_id) references sessions(id)
            );
            """
        )
        self._ensure_tokens_column()
        self.db.executescript(
            """
            drop trigger if exists messages_tokens_ai;
            drop trigger if exists messages_tokens_ad;
            drop trigger if exists messages_tokens_au;
            drop table if exists messages_tokens_fts;
            create virtual table if not exists messages_fts using fts5(
              content, role, session_id, content='messages', content_rowid='rowid'
            );
            create virtual table if not exists messages_tokens_fts using fts5(
              tokens, role, session_id, message_id unindexed
            );
            create trigger if not exists messages_ai after insert on messages begin
              insert into messages_fts(rowid, content, role, session_id)
              values (new.rowid, new.content, new.role, new.session_id);
            end;
            create trigger if not exists messages_ad after delete on messages begin
              insert into messages_fts(messages_fts, rowid, content, role, session_id)
              values('delete', old.rowid, old.content, old.role, old.session_id);
            end;
            create trigger if not exists messages_au after update on messages begin
              insert into messages_fts(messages_fts, rowid, content, role, session_id)
              values('delete', old.rowid, old.content, old.role, old.session_id);
              insert into messages_fts(rowid, content, role, session_id)
              values (new.rowid, new.content, new.role, new.session_id);
            end;
            """
        )
        self._backfill_tokens()
        self._init_token_triggers()
        self._init_graph_schema()
        self.db.commit()

    def _ensure_tokens_column(self) -> None:
        columns = {row["name"] for row in self.db.execute("pragma table_info(messages)").fetchall()}
        if "tokens" not in columns:
            self.db.execute("alter table messages add column tokens text not null default ''")
            self.db.commit()

    def _backfill_tokens(self) -> None:
        rows = self.db.execute("select rowid, content from messages where tokens = ''").fetchall()
        if rows:
            self.db.executemany(
                "update messages set tokens = ? where rowid = ?",
                [(tokenize_text(row["content"]), row["rowid"]) for row in rows],
            )
        self.db.execute("delete from messages_tokens_fts")
        self.db.execute(
            """
            insert into messages_tokens_fts(tokens, role, session_id, message_id)
            select tokens, role, session_id, id from messages
            """
        )

    def _init_token_triggers(self) -> None:
        self.db.executescript(
            """
            create trigger if not exists messages_tokens_ai after insert on messages begin
              insert into messages_tokens_fts(tokens, role, session_id, message_id)
              values (new.tokens, new.role, new.session_id, new.id);
            end;
            create trigger if not exists messages_tokens_ad after delete on messages begin
              delete from messages_tokens_fts where message_id = old.id;
            end;
            create trigger if not exists messages_tokens_au after update on messages begin
              delete from messages_tokens_fts where message_id = old.id;
              insert into messages_tokens_fts(tokens, role, session_id, message_id)
              values (new.tokens, new.role, new.session_id, new.id);
            end;
            """
        )

    def _init_graph_schema(self) -> None:
        self.db.executescript(
            """
            create table if not exists graph_entities(
              id text primary key,
              name text not null,
              normalized_name text not null,
              kind text not null default 'concept',
              aliases_json text not null default '[]',
              created_at integer not null,
              updated_at integer not null,
              unique(normalized_name, kind)
            );
            create table if not exists graph_relations(
              id text primary key,
              source_id text not null,
              relation text not null,
              target_id text not null,
              session_id text not null default '',
              evidence_message_id text not null default '',
              weight real not null default 1.0,
              meta_json text not null default '{}',
              created_at integer not null,
              unique(source_id, relation, target_id, session_id, evidence_message_id),
              foreign key(source_id) references graph_entities(id),
              foreign key(target_id) references graph_entities(id)
            );
            create index if not exists graph_entities_name_idx on graph_entities(normalized_name);
            create index if not exists graph_relations_relation_idx on graph_relations(relation);
            create index if not exists graph_relations_session_idx on graph_relations(session_id);
            """
        )

    def start_session(self, title: str = "") -> str:
        session_id = str(uuid.uuid4())
        now = int(time.time())
        self.db.execute(
            "insert into sessions(id, title, created_at, updated_at) values (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        self.db.commit()
        return session_id

    def append_message(self, session_id: str, role: str, content: str, meta: dict | None = None) -> str:
        message_id = str(uuid.uuid4())
        now = int(time.time())
        self.db.execute(
            "insert or ignore into sessions(id, title, created_at, updated_at) values (?, '', ?, ?)",
            (session_id, now, now),
        )
        self.db.execute(
            "insert into messages(id, session_id, role, content, tokens, meta_json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, tokenize_text(content), json.dumps(meta or {}, ensure_ascii=False), now),
        )
        self.db.execute("update sessions set updated_at = ? where id = ?", (now, session_id))
        self._extract_graph_facts(session_id, role, content, message_id)
        self.db.commit()
        return message_id

    def search(self, query: str, limit: int = 10) -> list[dict]:
        rows = []
        for table in ("messages_fts", "messages_tokens_fts"):
            try:
                rows.extend(self._search_table(table, query, limit))
            except sqlite3.OperationalError:
                if table == "messages_tokens_fts":
                    rows.extend(self._search_table(table, build_match_query(query), limit))
                else:
                    raise
        return self._dedupe_rows(rows)[:limit]

    def search_text(self, text: str, limit: int = 10) -> list[dict]:
        return self.search(build_match_query(text), limit)

    def _search_table(self, table: str, query: str, limit: int) -> list[dict]:
        join_clause = "m.id = f.message_id" if table == "messages_tokens_fts" else "m.rowid = f.rowid"
        rows = self.db.execute(
            f"""
            select m.id, m.session_id, m.role, m.content, m.meta_json, m.created_at
            from {table} f
            join messages m on {join_clause}
            where {table} match ?
            order by bm25({table})
            limit ?
            """,
            (query, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def recent(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            """
            select id, session_id, role, content, meta_json, created_at
            from messages
            where session_id = ?
            order by created_at desc
            limit ?
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in reversed(rows)]

    def ingest_trace(self, session_id: str, trace: dict) -> None:
        self.append_message(session_id, "trace", json.dumps(trace, ensure_ascii=False), {"kind": "runtime_trace"})

    def upsert_entity(self, name: str, kind: str = "concept", aliases: list[str] | None = None) -> str:
        clean_name = clean_entity_name(name)
        if not clean_name:
            raise ValueError("entity name is empty")
        clean_kind = clean_entity_name(kind or "concept").lower() or "concept"
        normalized = normalize_entity_name(clean_name)
        now = int(time.time())
        row = self.db.execute(
            "select id, aliases_json from graph_entities where normalized_name = ? and kind = ?",
            (normalized, clean_kind),
        ).fetchone()
        if row:
            existing_aliases = json.loads(row["aliases_json"] or "[]")
            merged_aliases = merge_aliases(existing_aliases, aliases or [])
            self.db.execute(
                "update graph_entities set name = ?, aliases_json = ?, updated_at = ? where id = ?",
                (clean_name, json.dumps(merged_aliases, ensure_ascii=False), now, row["id"]),
            )
            self.db.commit()
            return row["id"]
        entity_id = str(uuid.uuid4())
        self.db.execute(
            """
            insert into graph_entities(id, name, normalized_name, kind, aliases_json, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, clean_name, normalized, clean_kind, json.dumps(aliases or [], ensure_ascii=False), now, now),
        )
        self.db.commit()
        return entity_id

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        session_id: str = "",
        evidence_message_id: str = "",
        source_kind: str = "concept",
        target_kind: str = "concept",
        weight: float = 1.0,
        meta: dict | None = None,
    ) -> str:
        clean_relation = normalize_relation(relation)
        if not clean_relation:
            raise ValueError("relation is empty")
        source_id = self.upsert_entity(source, source_kind)
        target_id = self.upsert_entity(target, target_kind)
        relation_id = str(uuid.uuid4())
        now = int(time.time())
        self.db.execute(
            """
            insert or ignore into graph_relations(
              id, source_id, relation, target_id, session_id, evidence_message_id, weight, meta_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation_id,
                source_id,
                clean_relation,
                target_id,
                session_id or "",
                evidence_message_id or "",
                weight,
                json.dumps(meta or {}, ensure_ascii=False),
                now,
            ),
        )
        self.db.commit()
        row = self.db.execute(
            """
            select id from graph_relations
            where source_id = ? and relation = ? and target_id = ? and session_id = ? and evidence_message_id = ?
            """,
            (source_id, clean_relation, target_id, session_id or "", evidence_message_id or ""),
        ).fetchone()
        return row["id"] if row else relation_id

    def search_graph(self, query: str, limit: int = 10) -> list[dict]:
        terms = tokenize_text(query).split()
        rows = self.db.execute(
            """
            select
              r.id,
              s.name as source,
              s.kind as source_kind,
              r.relation,
              t.name as target,
              t.kind as target_kind,
              r.session_id,
              r.evidence_message_id,
              r.weight,
              r.meta_json,
              r.created_at
            from graph_relations r
            join graph_entities s on s.id = r.source_id
            join graph_entities t on t.id = r.target_id
            order by r.created_at desc
            limit 500
            """
        ).fetchall()
        scored = []
        for row in rows:
            item = self._graph_row_to_dict(row)
            haystack = " ".join([item["source"], item["relation"], item["target"], item["source_kind"], item["target_kind"]]).lower()
            score = sum(1 for term in terms if term.lower() in haystack)
            if score or not terms:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1]["created_at"]), reverse=True)
        return [item for _, item in scored[:limit]]

    def graph_context(self, query: str, limit: int = 5) -> str:
        facts = self.search_graph(query, limit)
        return "\n".join(
            f"{item['source']} -[{item['relation']}]-> {item['target']} (session: {item['session_id'] or 'global'})"
            for item in facts
        )

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["meta"] = json.loads(item.pop("meta_json") or "{}")
        return item

    @staticmethod
    def _graph_row_to_dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["meta"] = json.loads(item.pop("meta_json") or "{}")
        return item

    @staticmethod
    def _dedupe_rows(rows: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            result.append(row)
        return result

    def _extract_graph_facts(self, session_id: str, role: str, content: str, message_id: str) -> None:
        if role not in {"user", "assistant"}:
            return
        for fact in extract_graph_facts(content, role):
            try:
                self.add_relation(
                    fact["source"],
                    fact["relation"],
                    fact["target"],
                    session_id=session_id,
                    evidence_message_id=message_id,
                    source_kind=fact.get("source_kind", "concept"),
                    target_kind=fact.get("target_kind", "concept"),
                    meta={"extractor": "heuristic", "role": role},
                )
            except ValueError:
                continue


def compact_context(messages: Iterable[dict], max_chars: int = 4000) -> str:
    parts = []
    total = 0
    for msg in messages:
        line = f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
        if total + len(line) > max_chars:
            break
        parts.append(line)
        total += len(line)
    return "\n".join(parts)


def tokenize_text(text: str) -> str:
    tokens: list[str] = []
    seen = set()

    def add(token: str) -> None:
        token = token.strip().lower()
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)

    for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            add(part)
            chars = list(part)
            for char in chars:
                add(char)
            for size in range(2, 5):
                for idx in range(0, max(0, len(chars) - size + 1)):
                    add("".join(chars[idx : idx + size]))
        else:
            add(part)
    return " ".join(tokens)


def build_match_query(text: str, max_terms: int = 16) -> str:
    terms = tokenize_text(text).split()
    if not terms:
        return '"task"'
    return " OR ".join(f'"{escape_match_term(term)}"' for term in terms[:max_terms])


def escape_match_term(term: str) -> str:
    return term.replace('"', '""')


def extract_graph_facts(text: str, role: str = "user") -> list[dict]:
    facts: list[dict] = []
    if role == "user":
        for pattern in (
            r"\bI prefer ([^.。;\n]+)",
            r"\bI like ([^.。;\n]+)",
            r"\bI usually use ([^.。;\n]+)",
            r"\bI use ([^.。;\n]+)",
        ):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                target = clean_entity_name(match.group(1))
                if target:
                    facts.append({
                        "source": "user",
                        "source_kind": "person",
                        "relation": "prefers",
                        "target": target,
                        "target_kind": "preference",
                    })
        for pattern in (
            r"我(?:更)?(?:喜欢|偏好|希望使用)([^。；;\n]+)",
            r"我(?:通常)?使用([^。；;\n]+)",
        ):
            for match in re.finditer(pattern, text):
                target = clean_entity_name(match.group(1))
                if target:
                    facts.append({
                        "source": "user",
                        "source_kind": "person",
                        "relation": "prefers",
                        "target": target,
                        "target_kind": "preference",
                    })

    for pattern in (
        r"\bproject\s+([A-Za-z0-9_\-\u4e00-\u9fff]+)\s+(?:uses|adopts|depends on)\s+([^.。;\n]+)",
        r"项目\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)\s*(?:使用|采用|依赖)([^。；;\n]+)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            source = clean_entity_name(match.group(1))
            target = clean_entity_name(match.group(2))
            if source and target:
                facts.append({
                    "source": source,
                    "source_kind": "project",
                    "relation": "uses",
                    "target": target,
                    "target_kind": "technology",
                })
    return dedupe_facts(facts)


def dedupe_facts(facts: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for fact in facts:
        key = (fact.get("source"), fact.get("relation"), fact.get("target"))
        if key in seen:
            continue
        seen.add(key)
        result.append(fact)
    return result


def clean_entity_name(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text)).strip(" .。,:：;；-")
    return value[:120]


def normalize_entity_name(text: str) -> str:
    return re.sub(r"\s+", " ", clean_entity_name(text).lower())


def normalize_relation(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", str(text).strip().lower()).strip("_")


def merge_aliases(existing: list[str], incoming: list[str]) -> list[str]:
    result = []
    seen = set()
    for alias in [*existing, *incoming]:
        clean = clean_entity_name(alias)
        key = normalize_entity_name(clean)
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result[:20]
