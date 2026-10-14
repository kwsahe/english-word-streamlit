"""학습 기록 저장소.

- LocalStore: Supabase 미설정 시 기본값. 로컬 SQLite 파일(단일 사용자 'local').
- SupabaseStore: 로그인 사용자 세션(RLS 적용)으로 Supabase에 저장. service_role 키는 쓰지 않는다.

두 구현은 같은 메서드 계약을 따른다. 특히 record_review는 Supabase RPC
`public.record_review`와 동일한 의미(멱등 attempt_id + version CAS + 원자적 저장)를 가진다.
"""
import json
import sqlite3
import uuid
from datetime import datetime

from services.config import parse_dt, to_utc_iso

PAGE = 1000  # PostgREST 기본 최대 행 수


class StoreError(Exception):
    """저장 실패(네트워크/권한 등). 화면에는 '저장되지 않음'으로 표시해야 한다."""


def _progress_row(r: dict) -> dict:
    card = r["fsrs_card"]
    return {
        "word_id": str(r["word_id"]),
        "fsrs_card": json.loads(card) if isinstance(card, str) else card,
        "due_at": parse_dt(r["due_at"]),
        "last_review_at": parse_dt(r.get("last_review_at")),
        "review_count": r["review_count"],
        "lapse_count": r["lapse_count"],
        "version": r["version"],
    }


# ────────────────────────────────────────────────────────────────────
LOCAL_SCHEMA = """
create table if not exists word_progress (
    user_id text not null, word_id text not null, fsrs_card text not null, due_at text not null,
    last_review_at text, review_count integer not null default 0, lapse_count integer not null default 0,
    version integer not null default 1, updated_at text not null, primary key (user_id, word_id));
create index if not exists word_progress_due_idx on word_progress (user_id, due_at);
create table if not exists review_events (
    event_id text primary key, attempt_id text not null unique, user_id text not null, word_id text not null,
    session_id text, mode text not null, correct integer, rating integer not null check (rating between 1 and 4),
    duration_ms integer, device_type text, due_before text, due_after text not null, created_at text not null);
create index if not exists review_events_user_time_idx on review_events (user_id, created_at);
create table if not exists test_sessions (
    session_id text primary key, user_id text not null, mode text not null, total integer not null,
    correct integer not null, started_at text, finished_at text not null);
create table if not exists writing_attempts (
    attempt_id text primary key, user_id text not null, word_id text not null, mode text not null,
    ocr_text text, confirmed_text text, feedback text not null default '{}', status text not null,
    correct integer, created_at text not null);
create table if not exists ai_cache (
    user_id text not null, cache_key text not null, feature text not null, model_id text not null,
    prompt_version text not null, result text not null, expires_at text, valid integer not null default 1,
    created_at text not null, primary key (user_id, cache_key));
create table if not exists ai_usage (
    request_id text primary key, user_id text not null, feature text not null, model_id text not null,
    tokens_in integer, tokens_out integer, status text not null, created_at text not null);
create index if not exists ai_usage_user_time_idx on ai_usage (user_id, created_at);
create table if not exists settings (user_id text primary key, data text not null);
"""


class LocalStore:
    kind = "local"

    def __init__(self, path: str, user_id: str = "local"):
        self.path = path
        self.user_id = user_id
        with self._connect() as con:
            con.executescript(LOCAL_SCHEMA)

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        return con

    def _rows(self, sql, params=()):
        con = self._connect()
        try:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()

    def _exec(self, sql, params=()):
        con = self._connect()
        try:
            con.execute(sql, params)
        finally:
            con.close()

    # ── 복습 상태 ──
    def get_progress(self) -> dict[str, dict]:
        rows = self._rows("select * from word_progress where user_id = ?", (self.user_id,))
        return {r["word_id"]: _progress_row(r) for r in rows}

    def get_progress_one(self, word_id: str) -> dict | None:
        rows = self._rows("select * from word_progress where user_id = ? and word_id = ?",
                          (self.user_id, str(word_id)))
        return _progress_row(rows[0]) if rows else None

    def record_review(self, *, attempt_id, word_id, expected_version, fsrs_card, due_at, reviewed_at,
                      rating, correct, mode, duration_ms=None, device_type=None, session_id=None,
                      due_before=None) -> str:
        con = self._connect()
        try:
            con.execute("begin immediate")  # 쓰기 잠금: 동시 제출을 직렬화
            if con.execute("select 1 from review_events where attempt_id = ?", (str(attempt_id),)).fetchone():
                con.execute("rollback")
                return "duplicate"
            card_json = json.dumps(fsrs_card)
            if expected_version == 0:
                cur = con.execute(
                    "insert or ignore into word_progress (user_id, word_id, fsrs_card, due_at, last_review_at,"
                    " review_count, lapse_count, version, updated_at) values (?,?,?,?,?,1,?,1,?)",
                    (self.user_id, str(word_id), card_json, to_utc_iso(due_at), to_utc_iso(reviewed_at),
                     int(rating == 1), to_utc_iso(reviewed_at)))
            else:
                cur = con.execute(
                    "update word_progress set fsrs_card = ?, due_at = ?, last_review_at = ?,"
                    " review_count = review_count + 1, lapse_count = lapse_count + ?, version = version + 1,"
                    " updated_at = ? where user_id = ? and word_id = ? and version = ?",
                    (card_json, to_utc_iso(due_at), to_utc_iso(reviewed_at), int(rating == 1),
                     to_utc_iso(reviewed_at), self.user_id, str(word_id), expected_version))
            if cur.rowcount == 0:
                con.execute("rollback")
                return "conflict"
            con.execute(
                "insert into review_events (event_id, attempt_id, user_id, word_id, session_id, mode, correct,"
                " rating, duration_ms, device_type, due_before, due_after, created_at)"
                " values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), str(attempt_id), self.user_id, str(word_id),
                 str(session_id) if session_id else None, mode, None if correct is None else int(correct),
                 rating, duration_ms, device_type, to_utc_iso(due_before) if due_before else None,
                 to_utc_iso(due_at), to_utc_iso(reviewed_at)))
            con.execute("commit")
            return "ok"
        except sqlite3.IntegrityError:
            con.execute("rollback")
            return "duplicate"
        except Exception:
            if con.in_transaction:
                con.execute("rollback")
            raise
        finally:
            con.close()

    # ── 이력 ──
    def list_events(self, since: datetime) -> list[dict]:
        rows = self._rows("select * from review_events where user_id = ? and created_at >= ? order by created_at",
                          (self.user_id, to_utc_iso(since)))
        for r in rows:
            r["correct"] = None if r["correct"] is None else bool(r["correct"])
            r["created_at"] = parse_dt(r["created_at"])
        return rows

    def add_writing_attempt(self, row: dict) -> None:
        self._exec(
            "insert or ignore into writing_attempts (attempt_id, user_id, word_id, mode, ocr_text, confirmed_text,"
            " feedback, status, correct, created_at) values (?,?,?,?,?,?,?,?,?,?)",
            (str(row["attempt_id"]), self.user_id, str(row["word_id"]), row["mode"], row.get("ocr_text"),
             row.get("confirmed_text"), json.dumps(row.get("feedback") or {}, ensure_ascii=False),
             row["status"], None if row.get("correct") is None else int(row["correct"]),
             to_utc_iso(row["created_at"])))

    def list_writing_attempts(self, since: datetime) -> list[dict]:
        rows = self._rows("select * from writing_attempts where user_id = ? and created_at >= ?",
                          (self.user_id, to_utc_iso(since)))
        for r in rows:
            r["feedback"] = json.loads(r["feedback"])
            r["correct"] = None if r["correct"] is None else bool(r["correct"])
        return rows

    def add_test_session(self, row: dict) -> None:
        self._exec(
            "insert or ignore into test_sessions (session_id, user_id, mode, total, correct, started_at, finished_at)"
            " values (?,?,?,?,?,?,?)",
            (str(row["session_id"]), self.user_id, row["mode"], row["total"], row["correct"],
             to_utc_iso(row["started_at"]) if row.get("started_at") else None, to_utc_iso(row["finished_at"])))

    def list_test_sessions(self, since: datetime) -> list[dict]:
        return self._rows("select * from test_sessions where user_id = ? and finished_at >= ?",
                          (self.user_id, to_utc_iso(since)))

    # ── AI 캐시 / 사용량 ──
    def cache_get(self, key: str, now: datetime) -> dict | None:
        rows = self._rows("select result, expires_at from ai_cache where user_id = ? and cache_key = ? and valid = 1",
                          (self.user_id, key))
        if not rows or (rows[0]["expires_at"] and parse_dt(rows[0]["expires_at"]) <= now):
            return None
        return json.loads(rows[0]["result"])

    def cache_put(self, key, *, feature, model_id, prompt_version, result, expires_at, now) -> None:
        self._exec(
            "insert or replace into ai_cache (user_id, cache_key, feature, model_id, prompt_version, result,"
            " expires_at, valid, created_at) values (?,?,?,?,?,?,?,1,?)",
            (self.user_id, key, feature, model_id, prompt_version, json.dumps(result, ensure_ascii=False),
             to_utc_iso(expires_at) if expires_at else None, to_utc_iso(now)))

    def cache_invalidate(self, key: str) -> None:
        self._exec("update ai_cache set valid = 0 where user_id = ? and cache_key = ?", (self.user_id, key))

    def log_ai_usage(self, row: dict) -> None:
        self._exec(
            "insert into ai_usage (request_id, user_id, feature, model_id, tokens_in, tokens_out, status, created_at)"
            " values (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.user_id, row["feature"], row["model_id"], row.get("tokens_in"),
             row.get("tokens_out"), row["status"], to_utc_iso(row["created_at"])))

    def list_ai_usage(self, since: datetime) -> list[dict]:
        return self._rows("select * from ai_usage where user_id = ? and created_at >= ?",
                          (self.user_id, to_utc_iso(since)))

    # ── 사용자 설정(일일 목표량 등) ──
    def get_settings(self) -> dict:
        rows = self._rows("select data from settings where user_id = ?", (self.user_id,))
        return json.loads(rows[0]["data"]) if rows else {}

    def save_settings(self, data: dict) -> None:
        self._exec("insert or replace into settings (user_id, data) values (?, ?)",
                   (self.user_id, json.dumps(data, ensure_ascii=False)))


# ────────────────────────────────────────────────────────────────────
class SupabaseStore:
    """로그인한 사용자의 supabase-py Client를 받아 RLS 범위 안에서만 읽고 쓴다."""
    kind = "supabase"

    def __init__(self, client, user_id: str):
        self.client = client
        self.user_id = str(user_id)

    def _run(self, query):
        try:
            return query.execute().data
        except Exception as exc:  # 네트워크·권한·제약 위반을 하나로 묶어 상위에서 '저장 실패'로 표시
            raise StoreError(str(exc)[:300]) from exc

    def _select_all(self, table: str, since: tuple[str, datetime] | None = None) -> list[dict]:
        """RLS가 본인 행만 돌려준다. since=(열, 시각)이면 그 시각 이후만."""
        out, start = [], 0
        while True:
            q = self.client.table(table).select("*")
            if since:
                q = q.gte(since[0], to_utc_iso(since[1]))
            batch = self._run(q.order(self._order_col(table)).range(start, start + PAGE - 1))
            out.extend(batch)
            if len(batch) < PAGE:
                return out
            start += PAGE

    @staticmethod
    def _order_col(table):
        return {"word_progress": "word_id", "vocabulary": "word_id", "profiles": "user_id",
                "ai_cache": "cache_key", "test_sessions": "finished_at"}.get(table, "created_at")

    # ── 복습 상태 ──
    def get_progress(self) -> dict[str, dict]:
        return {str(r["word_id"]): _progress_row(r) for r in self._select_all("word_progress")}

    def get_progress_one(self, word_id: str) -> dict | None:
        rows = self._run(self.client.table("word_progress").select("*").eq("word_id", str(word_id)))
        return _progress_row(rows[0]) if rows else None

    def record_review(self, *, attempt_id, word_id, expected_version, fsrs_card, due_at, reviewed_at,
                      rating, correct, mode, duration_ms=None, device_type=None, session_id=None,
                      due_before=None) -> str:
        data = self._run(self.client.rpc("record_review", {
            "p_attempt_id": str(attempt_id), "p_word_id": str(word_id), "p_expected_version": expected_version,
            "p_fsrs_card": fsrs_card, "p_due_at": to_utc_iso(due_at), "p_reviewed_at": to_utc_iso(reviewed_at),
            "p_rating": rating, "p_correct": correct, "p_mode": mode, "p_duration_ms": duration_ms,
            "p_device_type": device_type, "p_session_id": str(session_id) if session_id else None,
            "p_due_before": to_utc_iso(due_before) if due_before else None,
        }))
        return data["status"]

    # ── 이력 ──
    def list_events(self, since: datetime) -> list[dict]:
        rows = self._select_all("review_events", since=("created_at", since))
        for r in rows:
            r["created_at"] = parse_dt(r["created_at"])
        return rows

    def add_writing_attempt(self, row: dict) -> None:
        self._run(self.client.table("writing_attempts").upsert({
            "attempt_id": str(row["attempt_id"]), "word_id": str(row["word_id"]), "mode": row["mode"],
            "ocr_text": row.get("ocr_text"), "confirmed_text": row.get("confirmed_text"),
            "feedback": row.get("feedback") or {}, "status": row["status"], "correct": row.get("correct"),
            "created_at": to_utc_iso(row["created_at"]),
        }, on_conflict="attempt_id", ignore_duplicates=True))

    def list_writing_attempts(self, since: datetime) -> list[dict]:
        return self._select_all("writing_attempts", since=("created_at", since))

    def add_test_session(self, row: dict) -> None:
        self._run(self.client.table("test_sessions").upsert({
            "session_id": str(row["session_id"]), "mode": row["mode"], "total": row["total"],
            "correct": row["correct"],
            "started_at": to_utc_iso(row["started_at"]) if row.get("started_at") else None,
            "finished_at": to_utc_iso(row["finished_at"]),
        }, on_conflict="session_id", ignore_duplicates=True))

    def list_test_sessions(self, since: datetime) -> list[dict]:
        return self._select_all("test_sessions", since=("finished_at", since))

    # ── AI 캐시 / 사용량 ──
    def cache_get(self, key: str, now: datetime) -> dict | None:
        rows = self._run(self.client.table("ai_cache").select("result, expires_at")
                         .eq("cache_key", key).eq("valid", True))
        if not rows or (rows[0]["expires_at"] and parse_dt(rows[0]["expires_at"]) <= now):
            return None
        return rows[0]["result"]

    def cache_put(self, key, *, feature, model_id, prompt_version, result, expires_at, now) -> None:
        self._run(self.client.table("ai_cache").upsert({
            "cache_key": key, "feature": feature, "model_id": model_id, "prompt_version": prompt_version,
            "result": result, "expires_at": to_utc_iso(expires_at) if expires_at else None,
            "valid": True, "created_at": to_utc_iso(now)}, on_conflict="user_id,cache_key"))

    def cache_invalidate(self, key: str) -> None:
        self._run(self.client.table("ai_cache").update({"valid": False}).eq("cache_key", key))

    def log_ai_usage(self, row: dict) -> None:
        self._run(self.client.table("ai_usage").insert({
            "feature": row["feature"], "model_id": row["model_id"], "tokens_in": row.get("tokens_in"),
            "tokens_out": row.get("tokens_out"), "status": row["status"],
            "created_at": to_utc_iso(row["created_at"])}))

    def list_ai_usage(self, since: datetime) -> list[dict]:
        return self._select_all("ai_usage", since=("created_at", since))

    # ── 단어장 / 프로필 (Supabase 전용) ──
    def list_vocabulary(self) -> list[dict]:
        return self._select_all("vocabulary")

    def upsert_vocabulary(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), 500):
            self._run(self.client.table("vocabulary").upsert(rows[i:i + 500], on_conflict="word_id"))

    def delete_vocabulary(self, word_ids: list[str]) -> None:
        if word_ids:
            self._run(self.client.table("vocabulary").delete().in_("word_id", [str(w) for w in word_ids]))

    def get_profile(self) -> dict | None:
        rows = self._run(self.client.table("profiles").select("*").eq("user_id", self.user_id))
        return rows[0] if rows else None

    def ensure_profile(self) -> dict:
        profile = self.get_profile()
        if profile is None:
            self._run(self.client.table("profiles").upsert({"user_id": self.user_id},
                                                           on_conflict="user_id", ignore_duplicates=True))
            profile = self.get_profile()
        return profile

    def get_settings(self) -> dict:
        return (self.get_profile() or {}).get("settings") or {}

    def save_settings(self, data: dict) -> None:
        self._run(self.client.table("profiles").update({"settings": data}).eq("user_id", self.user_id))

    def save_legacy_state(self, state: dict, mark_imported: bool = False, now: datetime | None = None) -> None:
        patch = {"legacy_state": state}
        if mark_imported:
            patch["legacy_imported_at"] = to_utc_iso(now)
        self._run(self.client.table("profiles").update(patch).eq("user_id", self.user_id))
