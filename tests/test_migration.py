import json
import uuid
from datetime import datetime, timezone

from conftest import ROOT
from services import migrate

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class MemoryStore:
    """import 계약 확인용 인메모리 저장소 (SupabaseStore와 같은 메서드)."""
    def __init__(self, user_id):
        self.user_id, self.rows, self.profile, self.upserts = user_id, {}, None, 0

    def list_vocabulary(self):
        return list(self.rows.values())

    def upsert_vocabulary(self, rows):
        self.upserts += len(rows)
        for r in rows:
            self.rows[r["word_id"]] = json.loads(json.dumps(r))   # DB 왕복처럼 JSON 직렬화

    def ensure_profile(self):
        self.profile = self.profile or {"user_id": self.user_id, "legacy_state": {}, "legacy_imported_at": None}
        return self.profile

    def save_legacy_state(self, state, mark_imported=False, now=None):
        self.profile["legacy_state"] = state
        if mark_imported:
            self.profile["legacy_imported_at"] = now.isoformat()


def test_excel_import_preserves_every_row_and_is_idempotent():
    words = migrate.read_excel_words(str(ROOT / "Word.xlsx"))
    assert len(words) > 700 and len({w["no"] for w in words}) == len(words)
    store = MemoryStore(str(uuid.uuid4()))
    rep = migrate.import_vocabulary(store, words)
    assert rep["inserted"] == len(words) == rep["db_count"]
    assert rep["source_checksum"] == rep["db_checksum"]
    assert len(store.rows) == len(words)        # 같은 철자 다의어도 병합하지 않음
    again = migrate.import_vocabulary(store, words)
    assert again["inserted"] == 0 and again["skipped_existing"] == len(words)
    assert len(store.rows) == len(words) and store.upserts == len(words)


def test_word_uuid_is_deterministic_per_owner():
    a = migrate.word_uuid("u1", 7)
    assert a == migrate.word_uuid("u1", 7)
    assert len({a, migrate.word_uuid("u2", 7), migrate.word_uuid(None, 7)}) == 3
    rows = migrate.vocabulary_rows([{"no": 7, "word": "x", "meaning": "", "example": "", "category": ""}], "u1")
    assert rows[0]["word_id"] == a and rows[0]["category"] == "기타"


def test_import_does_not_overwrite_user_edits():
    words = [{"no": 1, "word": "alpha", "meaning": "원래", "example": "", "category": "A"}]
    store = MemoryStore("u")
    migrate.import_vocabulary(store, words)
    wid = migrate.word_uuid("u", 1)
    store.rows[wid]["meaning"] = "사용자 수정"
    migrate.import_vocabulary(store, words)
    assert store.rows[wid]["meaning"] == "사용자 수정"


def test_legacy_progress_imported_once_without_fake_fsrs():
    progress = {"memorized": [1, 999], "wrong": [2], "correct": [3],
                "sessions": [{"date": "2026-04-09 16:56", "score": 90}]}
    store = MemoryStore("u")
    assert migrate.import_legacy_progress(store, progress, {1, 2, 3}, NOW) == "imported"
    state = store.profile["legacy_state"]
    assert state["memorized"] == [1] and state["wrong"] == [2] and state["correct"] == [3]
    assert len(state["sessions"]) == 1
    assert migrate.import_legacy_progress(store, progress, {1, 2, 3}, NOW) == "already_imported"
    assert len(store.profile["legacy_state"]["sessions"]) == 1


def test_merge_legacy_union_and_session_dedupe():
    a = {"memorized": [1], "wrong": [2], "correct": [3], "sessions": [{"date": "1", "score": 1}]}
    b = {"memorized": [4], "wrong": [3], "correct": [5], "sessions": [{"date": "1", "score": 1}, {"date": "2"}]}
    m = migrate.merge_legacy(a, b)
    assert m["memorized"] == [1, 4] and m["wrong"] == [2, 3] and m["correct"] == [5]
    assert len(m["sessions"]) == 2


def test_real_progress_json_has_no_loss():
    path = ROOT / "progress.json"
    if not path.exists():
        return
    progress = json.loads(path.read_text(encoding="utf-8"))
    nos = {w["no"] for w in migrate.read_excel_words(str(ROOT / "Word.xlsx"))}
    state = migrate.legacy_state(progress, nos)
    for key in ("memorized", "wrong", "correct"):
        assert len(state[key]) == len(set(progress[key]))
    assert len(state["sessions"]) == len(progress["sessions"])


def test_supabase_import_roundtrip(supabase_user):
    words = migrate.read_excel_words(str(ROOT / "Word.xlsx"))
    _, store = supabase_user()
    rep = migrate.import_vocabulary(store, words)
    assert rep["db_count"] == len(words) and rep["source_checksum"] == rep["db_checksum"]
    assert migrate.import_vocabulary(store, words)["inserted"] == 0
