from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fsrs import Card

from services import study
from services.store import LocalStore

SEOUL = ZoneInfo("Asia/Seoul")
T0 = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)


def test_rating_changes_due_and_json_roundtrip(tmp_path):
    preview = study.preview_due(None, T0)
    assert preview[1] < preview[3] < preview[4]          # Again < Good < Easy
    store = LocalStore(str(tmp_path / "t.db"))
    res = study.submit_review(store, word_id="w1", rating=4, mode="test", correct=True, now=T0)
    assert res["status"] == "ok" and res["due_at"] == preview[4]
    row = store.get_progress_one("w1")
    card = Card.from_dict(row["fsrs_card"])
    assert card.to_dict() == row["fsrs_card"]               # 직렬화 왕복
    assert row["due_at"] == preview[4] and row["due_at"].tzinfo is not None


def test_all_ratings_accepted_and_invalid_rejected(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    for r in (1, 2, 3, 4):
        assert study.submit_review(store, word_id=f"w{r}", rating=r, mode="t", correct=r > 1, now=T0)["status"] == "ok"
    assert store.get_progress_one("w1")["lapse_count"] == 1
    try:
        study.submit_review(store, word_id="x", rating=5, mode="t", correct=True, now=T0)
        raise AssertionError("rating 5 허용됨")
    except ValueError:
        pass


def test_seoul_day_boundary_and_month_end():
    # 서울 2026-10-31 23:30 = UTC 14:30 → 오늘은 10/31, 내일 00:00(KST) = UTC 10/31 15:00
    now = datetime(2026, 10, 31, 14, 30, tzinfo=timezone.utc)
    start, end = study.day_bounds(now, SEOUL)
    assert start == datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)
    # 서울 새벽 00:30 (UTC 전날 15:30)은 새 날짜로 계산
    start2, _ = study.day_bounds(datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc), SEOUL)
    assert start2.astimezone(SEOUL).date().isoformat() == "2026-11-02"


def test_queue_priority_and_no_fake_dates_for_legacy():
    words = [{"id": f"w{i}", "no": i} for i in range(1, 7)]
    now = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)
    def row(due, lapses=0):
        return {"due_at": due, "lapse_count": lapses, "fsrs_card": {}, "version": 1}
    progress = {
        "w1": row(now - timedelta(minutes=5)),      # 오늘 만기(지금 가능)
        "w2": row(now - timedelta(days=3)),         # 기한 지남
        "w3": row(now + timedelta(days=5), lapses=3),  # 반복 오답(만기 아님)
        "w5": row(now + timedelta(minutes=10)),     # Again 직후: 오늘 10분 뒤 → 아직 출제 안 함
    }
    q = study.build_today_queue(words, progress, now, SEOUL, new_limit=2, legacy_wrong={6})
    assert [w["id"] for w in q["queue"]] == ["w2", "w1", "w6", "w4"]   # 기한지남 → 지금 만기 → 새(legacy 오답 우선)
    assert [w["id"] for w in q["repeat_wrong"]] == ["w3"]
    assert [w["id"] for w in q["later_today"]] == ["w5"]
    assert q["new_total"] == 2
    # legacy 오답 단어도 FSRS 기록은 없음(새 카드 취급)
    assert "w6" not in progress


def test_new_card_due_immediately():
    assert study.card_from_progress(None, T0).due == T0
