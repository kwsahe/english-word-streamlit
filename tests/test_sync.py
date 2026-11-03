"""미전송 큐: 데이터 직렬화 · 멱등 재전송 · 새로고침(새 세션) 후 복원."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from services import sync
from services.store import LocalStore, StoreError

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def item(aid="11111111-1111-4111-8111-111111111111", writing=True):
    return sync.review_item(word_id="w", rating=3, mode="today:플래시카드", correct=True, attempt_id=aid, now=T0,
                            duration_ms=1200, device_type="tablet",
                            writing={"attempt_id": aid, "word_id": "w", "mode": "spell", "ocr_text": "x",
                                     "confirmed_text": "y", "status": "ocr", "correct": True, "created_at": T0}
                            if writing else None)


def test_roundtrip_json_and_apply_is_idempotent(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    restored = sync.loads(sync.dumps([item()]))          # 브라우저 보관 → 새로고침 후 복원
    assert restored == [item()]
    assert sync.apply(store, restored[0])["status"] == "ok"
    assert sync.apply(store, restored[0])["status"] == "duplicate"
    assert len(store.list_events(T0 - timedelta(days=1))) == 1
    assert len(store.list_writing_attempts(T0 - timedelta(days=1))) == 1
    ts = sync.test_session_item({"session_id": "s1", "mode": "4지선다", "total": 3, "correct": 2, "finished_at": T0})
    sync.apply(store, sync.loads(sync.dumps([ts]))[0])
    sync.apply(store, ts)
    assert len(store.list_test_sessions(T0 - timedelta(days=1))) == 1


def test_merge_dedupes_and_loads_is_tolerant():
    a, b = item("a"), item("b")
    assert [i["id"] for i in sync.merge([a], [a, b])] == ["a", "b"]
    assert sync.dumps([]) == "" and sync.loads("") == [] and sync.loads("{broken") == []
    assert sync.loads(json.dumps([{"op": "drop_table"}, {"op": "review"}])) == []   # 모르는/불완전 항목 무시


def test_failed_save_is_queued_persisted_and_retried_after_refresh(app_test, data_copy, monkeypatch):
    """저장 실패 → 큐 + 브라우저 보관 → (새로고침) 새 세션에서 복원 → 재전송 1회 반영."""
    from views import account
    browser = {}                                          # 가짜 localStorage

    def fake_local_storage(storage_key, *, key, write=None, report=True):
        if isinstance(write, str):
            browser.pop(storage_key, None) if write == "" else browser.__setitem__(storage_key, write)
        return browser.get(storage_key, "") if report else None
    monkeypatch.setattr(account, "local_storage", fake_local_storage)

    real = LocalStore.record_review
    monkeypatch.setattr(LocalStore, "record_review", lambda self, **kw: (_ for _ in ()).throw(StoreError("offline")))
    at = app_test()
    at.button(key="today_show").click().run()
    at.button(key="today_rate_3").click().run()
    assert len(at.session_state.wl_pending) == 1
    at.run()                                             # 다음 실행에서 브라우저에 기록
    stored = sync.loads(browser.get("wl_pending:local"))
    assert len(stored) == 1 and stored[0]["op"] == "review"
    assert any("미전송 1건" in e.value and "새로고침해도 유지" in e.value for e in at.sidebar.error)

    monkeypatch.setattr(LocalStore, "record_review", real)   # 네트워크 복구
    at2 = app_test()                                      # 새로고침 = 새 세션
    assert len(at2.session_state.wl_pending) == 1         # 브라우저 보관분 복원
    at2.sidebar.button(key="wl_retry").click().run()
    assert at2.session_state.wl_pending == []
    con = sqlite3.connect(data_copy / "wordloop.db")
    try:
        assert con.execute("select count(*) from review_events").fetchone()[0] == 1
    finally:
        con.close()
    at2.run()
    assert "wl_pending:local" not in browser              # 비면 브라우저에서도 삭제


@pytest.mark.parametrize("bad", ["not json", json.dumps({"op": "review"})])
def test_corrupt_browser_value_does_not_break_app(app_test, monkeypatch, bad):
    from views import account
    monkeypatch.setattr(account, "local_storage", lambda *a, **k: bad)
    at = app_test()
    assert at.session_state.wl_pending == []
