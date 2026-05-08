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

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
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
