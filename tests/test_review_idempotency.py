import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services import study
from services.store import LocalStore, StoreError

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _events(store):
    return store.list_events(T0 - timedelta(days=1))


def test_duplicate_attempt_recorded_once(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    aid = str(uuid.uuid4())
    first = study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, attempt_id=aid, now=T0)
    again = study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, attempt_id=aid,
                                now=T0 + timedelta(minutes=5))
    assert (first["status"], again["status"]) == ("ok", "duplicate")
    assert len(_events(store)) == 1
    row = store.get_progress_one("w")
    assert row["version"] == 1 and row["review_count"] == 1


def test_two_devices_same_attempt_concurrently(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    aid = str(uuid.uuid4())
    results = []

    def submit():
        results.append(study.submit_review(store, word_id="w", rating=1, mode="m", correct=False,
                                           attempt_id=aid, now=T0)["status"])
    threads = [threading.Thread(target=submit) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["duplicate"] * 5 + ["ok"]
    assert len(_events(store)) == 1 and store.get_progress_one("w")["review_count"] == 1


def test_two_devices_different_attempts_no_lost_update(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    outcomes = []

    def submit():
        try:
            outcomes.append(study.submit_review(store, word_id="w", rating=3, mode="m", correct=True,
                                                now=T0)["status"])
        except study.ReviewConflict:
            outcomes.append("conflict")   # 사용자에게 '저장 안 됨'으로 알림 (조용한 손실 아님)
    threads = [threading.Thread(target=submit) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok = outcomes.count("ok")
    row = store.get_progress_one("w")
    assert ok >= 2 and ok + outcomes.count("conflict") == 5
    assert row["review_count"] == ok == row["version"] == len(_events(store))   # 저장된 만큼만 반영


def test_conflict_rereads_latest_card_then_retries(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, now=T0)
    real_get = store.get_progress_one
    calls = {"n": 0}

    def stale_then_fresh(word_id):
        calls["n"] += 1
        row = real_get(word_id)
        if calls["n"] == 1:  # 첫 읽기 직후 다른 기기가 먼저 저장했다고 가정
            study.submit_review(store, word_id="w", rating=3, mode="other", correct=True,
                                now=T0 + timedelta(minutes=1))
        return row
    store.get_progress_one = stale_then_fresh
    res = study.submit_review(store, word_id="w", rating=1, mode="m", correct=False, now=T0 + timedelta(minutes=2))
    assert res["status"] == "ok" and calls["n"] == 3   # 1차 읽기, 다른 기기 저장, 재시도 읽기
    row = real_get("w")
    assert row["version"] == 3 and row["review_count"] == 3 and row["lapse_count"] == 1


def test_persistent_conflict_raises_instead_of_silent_loss(tmp_path):
    class AlwaysConflict(LocalStore):
        def record_review(self, **kw):
            return "conflict"
    store = AlwaysConflict(str(tmp_path / "t.db"))
    with pytest.raises(study.ReviewConflict):
        study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, now=T0)
    assert _events(store) == []


def test_store_failure_surfaces_and_nothing_partial(tmp_path):
    class Broken(LocalStore):
        def record_review(self, **kw):
            raise StoreError("network down")
    store = Broken(str(tmp_path / "t.db"))
    with pytest.raises(StoreError):
        study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, now=T0)
    assert store.get_progress_one("w") is None and _events(store) == []


def test_supabase_rpc_idempotent_and_cas(supabase_user):
    from services.migrate import import_vocabulary
    _, store = supabase_user()
    import_vocabulary(store, [{"no": 1, "word": "alpha", "meaning": "알파", "example": "", "category": "기타"}])
    wid = store.list_vocabulary()[0]["word_id"]
    aid = str(uuid.uuid4())
    statuses = [study.submit_review(store, word_id=wid, rating=3, mode="m", correct=True, attempt_id=aid,
                                    now=T0)["status"] for _ in range(2)]
    assert statuses == ["ok", "duplicate"]
    assert len(store.list_events(T0 - timedelta(days=1))) == 1
    row = store.get_progress_one(wid)
    stale = store.record_review(attempt_id=str(uuid.uuid4()), word_id=wid, expected_version=row["version"] + 5,
                                fsrs_card=row["fsrs_card"], due_at=T0, reviewed_at=T0, rating=3,
                                correct=True, mode="m")
    assert stale == "conflict"
    assert store.get_progress_one(wid)["version"] == row["version"]


def test_supabase_concurrent_devices(supabase_user):
    from services.migrate import import_vocabulary
    _, store = supabase_user()
    import_vocabulary(store, [{"no": 1, "word": "beta", "meaning": "베타", "example": "", "category": "기타"}])
    wid = store.list_vocabulary()[0]["word_id"]
    aid = str(uuid.uuid4())
    results = []

    def submit(attempt):
        results.append(study.submit_review(store, word_id=wid, rating=3, mode="m", correct=True,
                                           attempt_id=attempt, now=T0)["status"])
    threads = [threading.Thread(target=submit, args=(aid,)) for _ in range(3)] + \
              [threading.Thread(target=submit, args=(str(uuid.uuid4()),)) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 3 and results.count("duplicate") == 2
    row = store.get_progress_one(wid)
    assert row["review_count"] == 3 and len(store.list_events(T0 - timedelta(days=1))) == 3
