"""계정 간 데이터 격리(RLS)와 권한 검증 — 실제 Supabase(Auth+PostgREST+Postgres)에서 실행.

로컬: `npx supabase start` 후
  WORDLOOP_TEST_SUPABASE_URL=http://127.0.0.1:55321
  WORDLOOP_TEST_SUPABASE_ANON_KEY=<supabase status의 anon/publishable key>
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services import study
from services.migrate import import_legacy_progress, import_vocabulary
from services.store import StoreError

T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)
PRIVATE_TABLES = ["profiles", "vocabulary", "word_progress", "review_events", "writing_attempts",
                  "test_sessions", "ai_cache", "ai_usage"]


def _seed(store):
    import_vocabulary(store, [{"no": 1, "word": "secret", "meaning": "비밀", "example": "", "category": "A"}])
    wid = store.list_vocabulary()[0]["word_id"]
    study.submit_review(store, word_id=wid, rating=3, mode="m", correct=True, now=T0)
    store.add_writing_attempt({"attempt_id": str(uuid.uuid4()), "word_id": wid, "mode": "spell",
                               "ocr_text": "secrel", "confirmed_text": "secret", "status": "ocr",
                               "correct": True, "created_at": T0})
    store.add_test_session({"session_id": str(uuid.uuid4()), "mode": "4지선다", "total": 2, "correct": 1,
                            "finished_at": T0})
    store.cache_put("k1", feature="example", model_id="m", prompt_version="v", result={"a": 1},
                    expires_at=None, now=T0)
    store.log_ai_usage({"feature": "example", "model_id": "m", "status": "ok", "created_at": T0})
    import_legacy_progress(store, {"memorized": [1], "wrong": [], "correct": [], "sessions": []}, {1}, T0)
    return wid


def test_user_b_cannot_read_user_a_rows(supabase_user):
    client_a, a = supabase_user()
    client_b, b = supabase_user()
    wid = _seed(a)
    for table in PRIVATE_TABLES:
        assert client_a.table(table).select("*").execute().data, f"A는 자신의 {table}를 봐야 함"
        assert client_b.table(table).select("*").execute().data == [], f"B에게 A의 {table} 노출"
    assert b.get_progress() == {} and b.list_events(T0 - timedelta(days=1)) == []
    assert b.cache_get("k1", T0) is None
    # B는 A의 단어에 복습을 기록할 수 없다 (RPC 안에서 RLS 조회로 차단)
    with pytest.raises(StoreError):
        study.submit_review(b, word_id=wid, rating=3, mode="m", correct=True, now=T0)
    assert a.get_progress_one(wid)["review_count"] == 1


def test_user_b_cannot_modify_or_spoof_user_a(supabase_user):
    client_a, a = supabase_user()
    client_b, b = supabase_user()
    wid = _seed(a)
    client_b.table("vocabulary").update({"meaning": "탈취"}).eq("word_id", wid).execute()
    client_b.table("vocabulary").delete().eq("word_id", wid).execute()
    assert a.list_vocabulary()[0]["meaning"] == "비밀"
    # user_id를 남의 것으로 위조한 insert는 RLS with check로 거부
    with pytest.raises(Exception):
        client_b.table("vocabulary").insert({"owner_user_id": a.user_id, "word": "x"}).execute()
    with pytest.raises(Exception):
        client_b.table("ai_usage").insert({"user_id": a.user_id, "feature": "f", "model_id": "m",
                                           "status": "ok"}).execute()
    # 불변 이력: 본인도 review_events 수정·삭제 불가 (권한 자체가 없음)
    with pytest.raises(Exception):
        client_a.table("review_events").delete().eq("user_id", a.user_id).execute()
    with pytest.raises(Exception):
        client_a.table("review_events").update({"rating": 4}).eq("user_id", a.user_id).execute()
    assert len(a.list_events(T0 - timedelta(days=1))) == 1


def test_anon_role_has_no_access(supabase_user, anon_client):
    _, a = supabase_user()
    _seed(a)
    for table in PRIVATE_TABLES:
        with pytest.raises(Exception):
            anon_client.table(table).select("*").execute()
    with pytest.raises(Exception):
        anon_client.rpc("record_review", {"p_attempt_id": str(uuid.uuid4())}).execute()


def test_same_account_two_devices_see_same_data(supabase_user):
    """PC에서 저장 → 태블릿(새 클라이언트, 같은 계정) 재조회 시 동일."""
    import os

    from supabase import ClientOptions, create_client

    from services.store import SupabaseStore
    client_pc, pc = supabase_user()
    wid = _seed(pc)
    email = client_pc.auth.get_user().user.email
    tablet_client = create_client(os.environ["WORDLOOP_TEST_SUPABASE_URL"],
                                  os.environ["WORDLOOP_TEST_SUPABASE_ANON_KEY"],
                                  options=ClientOptions(auto_refresh_token=False, persist_session=False))
    res = tablet_client.auth.sign_in_with_password({"email": email, "password": "test-password-123"})
    tablet = SupabaseStore(tablet_client, res.user.id)
    assert tablet.get_progress() == pc.get_progress()
    assert tablet.get_profile()["legacy_state"] == pc.get_profile()["legacy_state"]
    study.submit_review(tablet, word_id=wid, rating=1, mode="spen", correct=False, now=T0 + timedelta(days=1))
    assert pc.get_progress_one(wid)["review_count"] == 2   # 태블릿 저장이 PC에서 보임
    # 로그아웃 후에는 같은 클라이언트로 개인 기록을 읽을 수 없다
    tablet_client.auth.sign_out()
    with pytest.raises(Exception):   # anon 권한으로 돌아가 permission denied
        tablet_client.table("word_progress").select("*").execute()
